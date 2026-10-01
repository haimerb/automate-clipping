"""Tendencias de hashtags por plataforma, con caché en disco y TTL.

Objetivo: que las descripciones dejen de llevar los mismos 5 hashtags genéricos
en todos los videos y lleven hashtags que (a) salen del contenido del clip y
(b) aprovechan lo que está en tendencia ahora.

Diseño defensivo: este módulo NUNCA debe romper la generación de metadata.

- Si no hay red, si la API falla o si la respuesta viene vacía, se devuelve
  `[]` con un warning y el llamador sigue con los tags del LLM + heurístico.
- La caché evita llamar al proveedor en cada clip y respeta los rate limits.
- Ninguna fuente requiere credenciales: YouTube usa su API key opcional y el
  RSS público; TikTok usa el endpoint público de Creative Center (best-effort).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# TTL por defecto: las tendencias rotan cada 1-4 semanas, pero refrescar cada
# 6-24h mantiene el freshness sin quemar rate limits.
DEFAULT_TTL_SECONDS = 12 * 3600
_FETCH_TIMEOUT = 8.0

_HASHTAG_RE = re.compile(r"#[\w一-鿿]+", re.UNICODE)


def _cache_dir() -> Path:
    """Ruta de la caché: `<storage>/.cache`.

    Se replica la resolución de `main._resolve_storage` en vez de importar
    `main`: este módulo se importa desde `viral`, que `main` importa, y hacerlo
    al cargar el módulo cerraría el ciclo. La función es lazy (solo en runtime).

    No la barre `cleanup.py` (que solo toca `previous/` y `ai_tmp`), pero es
    diminuta y el TTL la invalida: son unos pocos KB por plataforma.
    """
    raw = os.environ.get("EDGETAPE_STORAGE") or (Path(__file__).resolve().parent.parent / "storage")
    d = Path(raw).expanduser() / ".cache"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache de tendencias no disponible: %s", exc)
    return d


def _region() -> str:
    return (os.environ.get("EDGETAPE_TRENDS_REGION") or "US").strip().upper()[:4]


def _ttl() -> int:
    try:
        return max(300, int(os.environ.get("EDGETAPE_TRENDS_TTL", DEFAULT_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _cache_path(platform: str) -> Path:
    return _cache_dir() / f"trends_{platform}_{_region()}.json"


def _read_cache(platform: str) -> list[str]:
    path = _cache_path(platform)
    try:
        if not path.exists():
            return []
        age = time.time() - path.stat().st_mtime
        if age > _ttl():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        tags = payload.get("tags") or []
        return [str(t).strip().lower() for t in tags if str(t).strip()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache de tendencias ilegible (%s): %s", path, exc)
        return []


def _write_cache(platform: str, tags: list[str]) -> None:
    path = _cache_path(platform)
    try:
        path.write_text(
            json.dumps({"tags": tags, "saved_at": int(time.time())}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("no se pudo escribir la cache de tendencias: %s", exc)


def _dedupe(tags: list[str], limit: int = 40) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        t = t.strip().lower().lstrip("#")
        # sin espacios ni caracteres de control; los hashtags no los llevan
        if not t or " " in t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _youtube_trends(client: httpx.Client) -> list[str]:
    """Tendencias de YouTube vía API key opcional + RSS público como red de seguridad."""
    tags: list[str] = []

    key = os.environ.get("EDGETAPE_YOUTUBE_API_KEY", "").strip()
    if key:
        try:
            resp = client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet",
                    "chart": "mostPopular",
                    "regionCode": _region(),
                    "maxResults": 50,
                    "key": key,
                },
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                snippet = item.get("snippet") or {}
                tags.extend(_HASHTAG_RE.findall(snippet.get("tags") or []))
                tags.extend(_HASHTAG_RE.findall(snippet.get("title") or ""))
                tags.extend(_HASHTAG_RE.findall(snippet.get("description") or ""))
        except Exception as exc:  # noqa: BLE001
            logger.info("tendencias de YouTube por API no disponibles: %s", exc)

    if not tags:
        # RSS público: funciona sin credenciales, es best-effort por diseño.
        try:
            resp = client.get(
                "https://www.youtube.com/feeds/trending.xml",
                headers={"Accept-Language": "es,en;q=0.8"},
            )
            resp.raise_for_status()
            tags.extend(_HASHTAG_RE.findall(resp.text))
        except Exception as exc:  # noqa: BLE001
            logger.info("RSS de tendencias de YouTube no disponible: %s", exc)

    return tags


def _tiktok_trends(client: httpx.Client) -> list[str]:
    """TikTok Creative Center es best-effort: no hay API pública estable.

    Se parsea el HTML en busca de hashtags y se filtran los de navegación
    (`fyp`, `tiktok`, `viral`...) que ya pone el selector de plataforma.
    """
    try:
        resp = client.get(
            "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en",
            headers={"Accept-Language": "en,es;q=0.8"},
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.info("tendencias de TikTok no disponibles: %s", exc)
        return []

    tags = _HASHTAG_RE.findall(resp.text)
    # el nav de Creative Center mete sus propios tags en el HTML
    skip = {"fyp", "tiktok", "viral", "trending", "ads", "business", "creativecenter"}
    return [t for t in tags if t.lstrip("#").lower() not in skip]


def get_trending_hashtags(platform: str) -> list[str]:
    """Hashtags en tendencia para `platform`, con caché. Devuelve [] si no hay red.

    Nunca lanza: la ausencia de tendencias degrada al LLM + heurístico.
    """
    if os.environ.get("EDGETAPE_TRENDS", "1") == "0":
        return []

    cached = _read_cache(platform)
    if cached:
        return cached

    try:
        with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
            if "youtube" in platform:
                tags = _youtube_trends(client)
            elif "tiktok" in platform:
                tags = _tiktok_trends(client)
            else:
                # Reels/FB: no hay fuente pública fiable, se usa YouTube como
                # señal secundaria (las tendencias cruzan plataformas).
                tags = _youtube_trends(client)
    except Exception as exc:  # noqa: BLE001
        logger.info("sin tendencias para %s: %s", platform, exc)
        return []

    clean = _dedupe(tags)
    if clean:
        _write_cache(platform, clean)
    else:
        logger.info("tendencias vacías para %s; se usará LLM + heurístico", platform)
    return clean


def enrich_tags(tags: list[str], platform: str, max_tags: int = 6) -> list[str]:
    """Mezcla los tags del LLM con 0-1 tendencia fresca.

    Regla: 3-6 tags. El LLM pone 2-4 específicos + plataforma; aquí solo se
    cuela UN trend si no duplica y si el presupuesto lo permite. No se revientan
    los 3-5 pandilla: más de 6 tags reduce la distribución.
    """
    base = _dedupe(list(tags), limit=max_tags)
    if len(base) >= max_tags:
        return base[:max_tags]

    for trend in get_trending_hashtags(platform):
        if trend in base:
            continue
        # un trend sustituye al tag más débil antes que aumentar el count
        if len(base) >= max_tags - 1 and len(base) > 2:
            base = base[:-1]
        base.append(trend)
        break
    return base[:max_tags]
