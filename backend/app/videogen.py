"""Proveedor opcional de material generado por IA para el motor de escenas.

El objetivo del proyecto es NO correr difusión de video en local (una RTX 2060
de 6 GB no alcanza para Wan/ComfyUI), así que este módulo es un adaptador
delgado a proveedores remotos. Todos son opcionales y configurables solo por
entorno; sin ninguno configurado devuelve `None` y el pipeline sigue con
Wikimedia y los fondos de marca.

Proveedores
-----------
1. **webhook** (`EDGETAPE_VIDEOGEN_MODE=webhook`): `POST` a la URL completa
   esperando `{"video_url": "..."}`. Para texto→video con endpoint propio.
2. **image** (`EDGETAPE_VIDEOGEN_MODE=image`, por defecto): endpoint
   OpenAI-compatible `POST {base}/images/generations`. Devuelve un frame que el
   montaje anima con Ken Burns.

Cadena (`EDGETAPE_VIDEOGEN_PROVIDERS`)
--------------------------------------
`auto` (por defecto) intenta, en orden: `webhook`, `image`, `hf`, `fal`,
`replicate`. Un proveedor que falla o no está configurado pasa al siguiente; el
primero que devuelva material gana. `EDGETAPE_VIDEOGEN_PROVIDERS=hf,image` fija
el orden. Esto permite tener un proveedor gratis de respaldo detrás de uno de
pago sin tocar código.

- **hf**: Hugging Face Inference API (LTX-Video / Wan están ahí). Se configura
  con `EDGETAPE_VIDEOGEN_HF_TOKEN`. Opcionalmente `EDGETAPE_VIDEOGEN_HF_SPACE`
  + `EDGETAPE_VIDEOGEN_HF_SPACE_TOKEN` para un Space propio con ZeroGPU.
- **fal**: fal.ai (`EDGETAPE_VIDEOGEN_FAL_KEY`).
- **replicate**: Replicate (`EDGETAPE_VIDEOGEN_REPLICATE_TOKEN`).

Presupuesto y caché
-------------------
Los proveedores de video son caros/lentos, así que hay dos topes:
`EDGETAPE_VIDEOGEN_MAX_SCENES` (llamado en `ai_generate._try_videogen`) y
`_max_generations_per_job` por prompt+proveedor, para que los reintentos del
mismo job no paguen dos veces lo mismo.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

import httpx

from .materials import _MAX_DOWNLOAD_BYTES, _UA  # mismo límite que el stock

logger = logging.getLogger(__name__)

_API_TIMEOUT = 90.0
_WEBHOOK_TIMEOUT = 600.0

# Orden de la cadena en modo `auto`. `webhook` primero porque es el que el
# usuario puede apuntar a un proveedor de texto→video de pago.
PROVIDER_ORDER = ("webhook", "image", "hf", "fal", "replicate")

_GENERATION_CACHE: dict[str, float] = {}


def _max_generations_per_job() -> int:
    """Tope duro de generaciones por proceso para no Neymar la cuota."""
    try:
        return max(0, int(os.environ.get("EDGETAPE_VIDEOGEN_MAX_GENERATIONS", "0")))
    except ValueError:
        return 0


def _generation_key(prompt: str, provider: str) -> str:
    return f"{provider}:{prompt.strip().lower()[:120]}"


def _generation_allowed(prompt: str, provider: str) -> bool:
    """Rate-limit por prompt: un reintento del mismo job no regenera lo mismo."""
    limit = _max_generations_per_job()
    if limit <= 0:
        return True
    key = _generation_key(prompt, provider)
    used = _GENERATION_CACHE.get(key, 0.0)
    if used >= limit:
        logger.info("videogen: %s ya genero %d veces para este prompt; se omite", provider, used)
        return False
    _GENERATION_CACHE[key] = used + 1
    return True


def is_configured() -> bool:
    """True si hay al menos un proveedor con credenciales o URL."""
    if os.environ.get("EDGETAPE_VIDEOGEN_BASE_URL"):
        return True
    return bool(os.environ.get("EDGETAPE_VIDEOGEN_HF_TOKEN")
                or os.environ.get("EDGETAPE_VIDEOGEN_HF_SPACE_TOKEN")
                or os.environ.get("EDGETAPE_VIDEOGEN_FAL_KEY")
                or os.environ.get("EDGETAPE_VIDEOGEN_REPLICATE_TOKEN"))


def _settings() -> tuple[str, str, str, str]:
    base = (os.environ.get("EDGETAPE_VIDEOGEN_BASE_URL") or "").rstrip("/")
    key = os.environ.get("EDGETAPE_VIDEOGEN_API_KEY") or ""
    model = os.environ.get("EDGETAPE_VIDEOGEN_MODEL") or ""
    mode = (os.environ.get("EDGETAPE_VIDEOGEN_MODE") or "image").strip().lower()
    return base, key, model, mode


def _provider_chain() -> tuple[str, ...]:
    """Orden efectivo de proveedores a intentar."""
    raw = (os.environ.get("EDGETAPE_VIDEOGEN_PROVIDERS") or "auto").strip().lower()
    if raw not in ("", "auto"):
        chain = tuple(p.strip() for p in raw.split(",") if p.strip())
        return tuple(p for p in chain if p in PROVIDER_ORDER) or ("image",)
    base, _key, _model, mode = _settings()
    if not base:
        return ("image",)
    return (mode,) if mode in PROVIDER_ORDER else ("image",)


def _headers(key: str) -> dict[str, str]:
    headers = {"User-Agent": _UA, "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _save_bytes(data: bytes, out: Path) -> Path | None:
    if len(data) < 1024:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def _download(client: httpx.Client, url: str, out: Path) -> Path | None:
    resp = client.get(url, headers={"User-Agent": _UA})
    resp.raise_for_status()
    if len(resp.content) > _MAX_DOWNLOAD_BYTES:
        raise RuntimeError(f"video generado demasiado grande: {len(resp.content)} bytes")
    return _save_bytes(resp.content, out)


def generate_video(
    prompt: str, size: tuple[int, int], out: Path, client: httpx.Client | None = None
) -> Path | None:
    """Clip de texto→video vía webhook. Devuelve la ruta (sin extensión) o None."""
    base, key, model, mode = _settings()
    if not base or mode != "webhook" or not prompt.strip():
        return None
    if not _generation_allowed(prompt, "webhook"):
        return None
    own = client is None
    c = client or httpx.Client(timeout=_WEBHOOK_TIMEOUT)
    try:
        body = {
            "model": model or None,
            "prompt": prompt,
            "seconds": 5,
            "aspect": "9:16" if size[1] >= size[0] else "16:9",
            "resolution": f"{size[0]}x{size[1]}",
        }
        resp = c.post(base, json={k: v for k, v in body.items() if v}, headers=_headers(key))
        resp.raise_for_status()
        url = (resp.json() or {}).get("video_url")
        if not url:
            logger.warning("videogen: la respuesta no trae video_url")
            return None
        path = _download(c, str(url), out)
        if path:
            logger.info("videogen: clip generado (%s)", prompt[:60])
        return path
    except Exception as exc:  # noqa: BLE001 — el proveedor IA nunca debe tumbar el job
        logger.warning("videogen (webhook) falló (%s); se sigue sin clip IA", exc)
        return None
    finally:
        if own:
            c.close()


def generate_image(
    prompt: str, size: tuple[int, int], out: Path, client: httpx.Client | None = None
) -> Path | None:
    """Frame generado por IA (endpoint OpenAI-compatible `/images/generations`)."""
    base, key, model, mode = _settings()
    if not base or mode == "webhook" or not prompt.strip():
        return None
    if not _generation_allowed(prompt, "image"):
        return None
    url = f"{base}/images/generations"
    own = client is None
    c = client or httpx.Client(timeout=_API_TIMEOUT)
    try:
        body = {
            "model": model or None,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        resp = c.post(
            url, json={k: v for k, v in body.items() if v}, headers=_headers(key)
        )
        resp.raise_for_status()
        first = ((resp.json() or {}).get("data") or [{}])[0]
        if first.get("b64_json"):
            path = _save_bytes(base64.b64decode(first["b64_json"]), out)
        elif first.get("url"):
            path = _download(c, str(first["url"]), out)
        else:
            logger.warning("videogen: la respuesta no trae b64_json ni url")
            return None
        if path:
            logger.info("videogen: frame generado (%s)", prompt[:60])
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("videogen (imagen) falló (%s); se sigue sin frame IA", exc)
        return None
    finally:
        if own:
            c.close()


# ── Proveedores alojados (cadena) ────────────────────────────────────

def _hf_generation(prompt: str, size: tuple[int, int]) -> dict | None:
    """Config para el router de Hugging Face. No hace la request."""
    token = os.environ.get("EDGETAPE_VIDEOGEN_HF_TOKEN") or ""
    if not token:
        return None
    return {
        "provider": "hf",
        "url": "https://router.huggingface.co/hf-inference/models/"
                + os.environ.get("EDGETAPE_VIDEOGEN_HF_MODEL", "LTX-Video/LTX-Video-0.9.7-distilled"),
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 180.0,
        "prompt": prompt,
        "size": size,
    }


def _fal_generation(prompt: str, size: tuple[int, int]) -> dict | None:
    key = os.environ.get("EDGETAPE_VIDEOGEN_FAL_KEY") or ""
    if not key:
        return None
    return {
        "provider": "fal",
        "url": "https://fal.run/"
                + os.environ.get("EDGETAPE_VIDEOGEN_FAL_MODEL", "fal-ai/ltx-video"),
        "headers": {"Authorization": f"Key {key}"},
        "timeout": 180.0,
        "prompt": prompt,
        "size": size,
    }


def _replicate_generation(prompt: str, size: tuple[int, int]) -> dict | None:
    token = os.environ.get("EDGETAPE_VIDEOGEN_REPLICATE_TOKEN") or ""
    if not token:
        return None
    return {
        "provider": "replicate",
        "url": "https://api.replicate.com/v1/predictions",
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 60.0,
        "poll": True,
        "prompt": prompt,
        "size": size,
    }


_HOSTED = {
    "hf": _hf_generation,
    "fal": _fal_generation,
    "replicate": _replicate_generation,
}


def _generate_hosted(
    provider: str, prompt: str, size: tuple[int, int], out: Path, client: httpx.Client
) -> Path | None:
    """Llama a un proveedor alojado (hf/fal/replicate) y guarda el asset.

    Cada proveedor tiene su forma de request/response; la normalización es
    quedarse con `video`/`image` si vienen como URL o base64.
    """
    build = _HOSTED.get(provider)
    if build is None:
        return None
    cfg = build(prompt, size)
    if cfg is None:
        return None
    if not _generation_allowed(prompt, provider):
        return None

    model = os.environ.get(f"EDGETAPE_VIDEOGEN_{provider.upper()}_MODEL", "")
    aspect = "9:16" if size[1] >= size[0] else "16:9"

    if provider == "replicate":
        # Replicate: POST predice, luego poll hasta succeeded/failed.
        resp = client.post(
            cfg["url"],
            json={"version": model, "input": {"prompt": prompt, "aspect_ratio": aspect}},
            headers=cfg["headers"],
        )
        resp.raise_for_status()
        prediction = resp.json()
        poll_url = (prediction.get("urls") or {}).get("get")
        if not poll_url:
            logger.warning("videogen (%s): la predicción no trae urls.get", provider)
            return None
        deadline = time.monotonic() + 300
        while prediction.get("status") in ("starting", "processing"):
            if time.monotonic() > deadline:
                logger.warning("videogen (%s): timeout esperando el video", provider)
                return None
            time.sleep(2.0)
            poll = client.get(poll_url, headers=cfg["headers"])
            poll.raise_for_status()
            prediction = poll.json()
            # Replicate omite `urls` en los polls posteriores
            poll_url = (prediction.get("urls") or {}).get("get") or poll_url
        if prediction.get("status") != "succeeded":
            logger.warning("videogen (%s): %s", provider, prediction.get("error"))
            return None
        url = prediction.get("output")
        if isinstance(url, list):
            url = url[0] if url else None
        if not url:
            return None
        path = _download(client, str(url), out)
    elif provider == "fal":
        resp = client.post(
            cfg["url"],
            json={"prompt": prompt, "aspect_ratio": aspect, "num_frames": 121},
            headers=cfg["headers"],
        )
        resp.raise_for_status()
        data = resp.json() or {}
        url = data.get("video") or (data.get("videos") or [{}])[0].get("url")
        if not url:
            return None
        path = _download(client, str(url), out)
    else:  # hf (text-to-video vía router; mismo shape que OpenAI images)
        resp = client.post(
            cfg["url"],
            json={"inputs": prompt},
            headers=cfg["headers"],
        )
        resp.raise_for_status()
        # router puede devolver video binario directo o un JSON con URLs
        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("video/") or ctype.startswith("image/"):
            path = _save_bytes(resp.content, out)
        else:
            data = resp.json() or {}
            url = None
            if isinstance(data, list):
                url = data[0].get("video") if isinstance(data[0], dict) else None
            elif isinstance(data, dict):
                url = data.get("video") or data.get("image")
            if url:
                path = _download(client, str(url), out)
            else:
                path = None
    if path:
        logger.info("videogen (%s): asset generado (%s)", provider, prompt[:60])
    return path


def generate_asset(
    prompt: str, size: tuple[int, int], out: Path, client: httpx.Client | None = None
) -> tuple[Path | None, bool]:
    """Recorre la cadena de proveedores hasta que uno devuelva material.

    Devuelve `(ruta, es_video)`; `(None, False)` si no hay proveedor, todos
    fallan, o el presupuesto está agotado. Nunca lanza.
    """
    if not is_configured() or not prompt.strip():
        return None, False

    own = client is None
    c = client or httpx.Client(timeout=_WEBHOOK_TIMEOUT)
    try:
        for provider in _provider_chain():
            try:
                if provider == "webhook":
                    path = generate_video(prompt, size, out, client=c)
                    if path:
                        return path, True
                elif provider == "image":
                    still = generate_image(prompt, size, out, client=c)
                    if still:
                        return still, False
                else:
                    hosted = _generate_hosted(provider, prompt, size, out, c)
                    if hosted:
                        # hosted devuelve video si el proveedor es de video
                        return hosted, provider in ("hf", "fal", "replicate")
            except Exception as exc:  # noqa: BLE001
                logger.warning("videogen (%s) falló (%s); probando el siguiente", provider, exc)
                continue
        return None, False
    finally:
        if own:
            c.close()
