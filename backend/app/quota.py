from __future__ import annotations

"""Cuotas diarias de proveedores gratis.

Los free tiers (Cloudflare FLUX, Hugging Face ZeroGPU, Gemini) se agotan y
devuelven 429. Llevar el contador en disco permite degradar antes de golpear la
API y avisar por `Job.warning` en vez de fallar en silencio.

El archivo se elige con `EDGETAPE_QUOTA_FILE`; si no está, se usa uno en el
directorio temporal del sistema. El reset es por fecha UTC.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_DEFAULT_PATH = Path(tempfile.gettempdir()) / "edgetape_quota.json"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _path() -> Path:
    raw = os.environ.get("EDGETAPE_QUOTA_FILE")
    return Path(raw) if raw else _DEFAULT_PATH


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save(data: dict) -> None:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("no se pudo guardar la cuota en %s (%s)", _path(), exc)


def remaining(provider: str, limit: int) -> int:
    """Unidades disponibles hoy para `provider` (nunca negativo)."""
    if limit <= 0:
        return 0
    with _LOCK:
        data = _load()
        entry = data.get(provider) or {}
        if entry.get("date") != _today():
            return limit
        used = int(entry.get("used") or 0)
        return max(0, limit - used)


def consume(provider: str, limit: int, amount: int = 1) -> bool:
    """Reserva `amount` unidades. False si no quedan (no escribe nada)."""
    if limit <= 0 or amount <= 0:
        return False
    with _LOCK:
        data = _load()
        today = _today()
        entry = data.get(provider) or {}
        used = int(entry.get("used") or 0) if entry.get("date") == today else 0
        if used + amount > limit:
            return False
        data[provider] = {"date": today, "used": used + amount}
        _save(data)
        return True


def snapshot() -> dict:
    with _LOCK:
        return _load()
