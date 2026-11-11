from __future__ import annotations

"""Video IA en free tier: Hugging Face ZeroGPU (image-to-video).

Se usa image-to-video sobre el still de la escena (FLUX/stock) para que el
movimiento quede anclado a una imagen coherente. ZeroGPU da ~5 min de GPU/día y
no pone watermark. El espacio y el `api_name` son configurables porque las
Spaces cambian: si falla, el pipeline sigue con la imagen.

`gradio_client` se importa de forma perezosa (nunca en el import path).
"""

import logging
import os
import shutil
from pathlib import Path

from .. import quota

logger = logging.getLogger(__name__)

_DEFAULT_SPACE = "Wan-AI/Wan2.2-I2V-A14B"
_DEFAULT_API = "/generate_video"
_DEFAULT_DAILY = 6


def _mode() -> str:
    return os.environ.get("EDGETAPE_VIDEO_PROVIDER", "off").strip().lower()


def is_configured() -> bool:
    if _mode() not in {"hf", "huggingface", "auto"}:
        return False
    return bool(os.environ.get("EDGETAPE_HF_TOKEN"))


def _daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("EDGETAPE_HF_VIDEO_DAILY", str(_DEFAULT_DAILY))))
    except ValueError:
        return _DEFAULT_DAILY


def image_to_video(
    image: Path,
    prompt: str,
    out: Path,
    *,
    seconds: float | None = None,
) -> Path | None:
    """Anima `image` con el prompt. Nunca lanza; None si no hay cupo/space."""
    if not is_configured():
        return None
    if not quota.consume("hf-zerogpu", _daily_limit()):
        logger.warning("cuota diaria de HF ZeroGPU agotada")
        return None
    space = os.environ.get("EDGETAPE_HF_VIDEO_SPACE", _DEFAULT_SPACE)
    api_name = os.environ.get("EDGETAPE_HF_VIDEO_API", _DEFAULT_API)
    token = os.environ["EDGETAPE_HF_TOKEN"]
    try:
        from gradio_client import Client, handle_file

        client = Client(space, hf_token=token)
        kwargs = {"image": handle_file(str(image)), "prompt": prompt}
        if seconds:
            kwargs["duration"] = float(seconds)
        result = client.predict(api_name=api_name, **kwargs)
        path = _result_path(result)
        if path is None:
            logger.warning("HF ZeroGPU no devolvió un video (%r)", result)
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)
        if out.exists() and out.stat().st_size > 1024:
            logger.info("video IA (HF ZeroGPU) · %s", prompt[:60])
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("HF ZeroGPU falló (%s)", exc)
    return None


def _result_path(result) -> Path | None:
    if isinstance(result, (str, os.PathLike)):
        p = Path(result)
        return p if p.exists() else None
    if isinstance(result, (tuple, list)):
        for item in result:
            found = _result_path(item)
            if found:
                return found
    if isinstance(result, dict):
        for key in ("video", "path", "name"):
            found = _result_path(result.get(key))
            if found:
                return found
    return None
