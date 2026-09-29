"""Proveedor opcional de video/imagen generado por IA para el motor de escenas.

El objetivo del proyecto es NO correr difusión de video en local (una RTX 2060 de
6 GB no alcanza), así que este módulo es un adaptador delgado a proveedores
remotos. Hay dos modos, ambos configurables solo por entorno:

1. **Imagen** (`EDGETAPE_VIDEOGEN_MODE=image`, por defecto): endpoint
   OpenAI-compatible `POST {base}/images/generations`. Sirve para(scene) cuando el
   catálogo de stock no trae nada utile, ya que devuelve un frame que el montaje
   anima con Ken Burns.
2. **Webhook** (`EDGETAPE_VIDEOGEN_MODE=webhook`): `POST` a la URL completa esperando
   `{"video_url": "..."}`. Pensado para proveedores de texto→video (Wan, Seedance,
   WaveSpeed, MiniMax…) que exponen un endpoint propio.

Ambos son opcionales: sin `EDGETAPE_VIDEOGEN_BASE_URL` el módulo devuelve `None`
y el pipeline sigue con Wikimedia y los fondos de marca.
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


def is_configured() -> bool:
    return bool(os.environ.get("EDGETAPE_VIDEOGEN_BASE_URL"))


def _settings() -> tuple[str, str, str, str]:
    base = (os.environ.get("EDGETAPE_VIDEOGEN_BASE_URL") or "").rstrip("/")
    key = os.environ.get("EDGETAPE_VIDEOGEN_API_KEY") or ""
    model = os.environ.get("EDGETAPE_VIDEOGEN_MODEL") or ""
    mode = (os.environ.get("EDGETAPE_VIDEOGEN_MODE") or "image").strip().lower()
    return base, key, model, mode


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


def generate_asset(
    prompt: str, size: tuple[int, int], out: Path, client: httpx.Client | None = None
) -> tuple[Path | None, bool]:
    """Intento único: primero clip (webhook) y, si no, frame (imagen).

    Devuelve `(ruta, es_video)`; `(None, False)` si no hay proveedor o falla.
    """
    if not is_configured():
        return None, False
    clip = generate_video(prompt, size, out, client=client)
    if clip is not None:
        return clip, True
    still = generate_image(prompt, size, out, client=client)
    return still, False
