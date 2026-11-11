from __future__ import annotations

"""Imágenes generadas con IA en free tiers, sin watermark.

Cloudflare Workers AI (FLUX schnell) es el proveedor por defecto: ~10.000
neuronas/día (≈170 imágenes) sin tarjeta. La respuesta puede venir como JSON
con base64 o como bytes de imagen; se soportan ambas.
"""

import base64
import logging
import os
from pathlib import Path

import httpx

from .. import quota

logger = logging.getLogger(__name__)

_CF_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
_DEFAULT_DAILY = 150


def _provider_mode() -> str:
    return os.environ.get("EDGETAPE_IMAGE_PROVIDER", "auto").strip().lower()


def cloudflare_configured() -> bool:
    return bool(
        os.environ.get("EDGETAPE_CLOUDFLARE_ACCOUNT_ID")
        and os.environ.get("EDGETAPE_CLOUDFLARE_API_TOKEN")
    )


def is_configured() -> bool:
    mode = _provider_mode()
    if mode in {"off", "none", "0", "stock"}:
        return False
    return cloudflare_configured()


def _daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("EDGETAPE_IMAGE_DAILY_LIMIT", str(_DEFAULT_DAILY))))
    except ValueError:
        return _DEFAULT_DAILY


def _style_prompt(prompt: str, size: tuple[int, int]) -> str:
    orientation = "vertical 9:16" if size[1] > size[0] else "horizontal 16:9"
    subject = (prompt or "").strip() or "cinematic scene"
    return (
        f"{subject}, cinematic lighting, photorealistic, "
        f"high detail, {orientation}, no text, no watermark, no logo"
    )


def _extract_image(resp: httpx.Response) -> tuple[bytes, str] | None:
    ctype = (resp.headers.get("content-type") or "").lower()
    if ctype.startswith("image/"):
        return resp.content, ctype
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        raw = result.get("image") or result.get("image_b64")
        if raw:
            return base64.b64decode(raw), "image/png"
        images = result.get("images") or []
        if images and isinstance(images[0], str):
            return base64.b64decode(images[0]), "image/png"
    if isinstance(result, str):
        return base64.b64decode(result), "image/png"
    return None


def generate_image(prompt: str, size: tuple[int, int], out: Path) -> Path | None:
    """Genera una imagen con FLUX. Nunca lanza."""
    if not is_configured():
        return None
    limit = _daily_limit()
    if not quota.consume("cloudflare-flux", limit):
        logger.warning("cuota diaria de Cloudflare FLUX agotada")
        return None
    account = os.environ["EDGETAPE_CLOUDFLARE_ACCOUNT_ID"]
    token = os.environ["EDGETAPE_CLOUDFLARE_API_TOKEN"]
    model = os.environ.get("EDGETAPE_CLOUDFLARE_IMAGE_MODEL", _CF_MODEL)
    url = _CF_URL.format(account=account, model=model)
    body = {"prompt": _style_prompt(prompt, size), "steps": 4}
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            logger.warning("Cloudflare FLUX %d: %s", resp.status_code, resp.text[:200])
            return None
        parsed = _extract_image(resp)
        if not parsed:
            logger.warning("Cloudflare FLUX devolvió un formato desconocido")
            return None
        data, ctype = parsed
        suffix = ".png" if "png" in ctype else ".jpg"
        path = out.with_suffix(suffix)
        path.write_bytes(data)
        if path.stat().st_size < 1024:
            path.unlink(missing_ok=True)
            return None
        logger.info("imagen IA (Cloudflare FLUX) · %s", prompt[:60])
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cloudflare FLUX falló (%s)", exc)
        return None
