"""Limitador de tasa en memoria (ventana deslizante) para proteger endpoints
sensibles: login/registro y creación de jobs.

Sin dependencias externas. Funciona por proceso; detrás de varios workers cada
uno lleva su propia cuenta. Para el despliegue actual (uvicorn de un proceso) es
suficiente. Se desactiva con `EDGETAPE_RATE_LIMIT=0`.
"""

from __future__ import annotations

import threading
import time
from collections import deque

_UNITS = {"s": 1.0, "sec": 1.0, "second": 1.0, "m": 60.0, "min": 60.0, "minute": 60.0, "h": 3600.0, "hour": 3600.0}


def parse_rate(spec: str, default: tuple[int, float] = (0, 0.0)) -> tuple[int, float]:
    """Convierte "20/min" o "30 per hour" en (máximo, ventana en segundos).

    Devuelve `default` si el formato no se entiende. Un máximo de 0 desactiva.
    """
    if not spec or not spec.strip():
        return default
    raw = spec.strip().lower()
    raw = raw.replace(" per ", "/").replace("per ", "/").replace(" per", "/").replace(" ", "")
    sep = "/" if "/" in raw else (":" if ":" in raw else None)
    if not sep:
        return default
    count_s, unit_s = raw.split(sep, 1)
    try:
        count = int(count_s)
    except ValueError:
        return default
    unit = unit_s.rstrip("s") if unit_s.rstrip("s") in _UNITS else unit_s
    if unit.isdigit():
        window = float(unit)
    else:
        window = _UNITS.get(unit)
    if window is None or count < 0:
        return default
    return count, window


class SlidingWindowLimiter:
    """Permite como máximo `max_events` eventos por `window_seconds` y clave."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_events > 0 and self.window > 0

    def hit(self, key: str) -> tuple[bool, float]:
        """Registra un evento. Devuelve (permitido, segundos_hasta_reintentar)."""
        if not self.enabled:
            return True, 0.0
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            queue = self._events.setdefault(key, deque())
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self.max_events:
                retry_after = self.window - (now - queue[0])
                return False, max(retry_after, 0.0)
            queue.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
