from __future__ import annotations

"""Material de stock (b-roll real) para los videos generados con IA.

Busca clips de video reales con movimiento en Pexels y Pixabay (ambas APIs son
gratis) para acompañar cada escena del guion. A diferencia de las imágenes
sueltas de Wikimedia, el video de stock da la sensación de "video de verdad"
que los generadores tipo MoneyPrinterTurbo logran en CPU sin GPU.

Reglas de oro:
- Nunca revienta: sin red, sin claves o ante errores, devuelve lo que pueda.
- Deduplica por id del proveedor: una escena no repite un asset ya usado.
- Prioriza la orientación del formato (vertical / horizontal) y evita archivos
  gigantes (tope de descarga configurable).
"""

import logging
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"
PIXABAY_PHOTO_URL = "https://pixabay.com/api/"

_API_TIMEOUT = 12.0
_DOWNLOAD_TIMEOUT = 60.0
_MAX_DOWNLOAD_BYTES = 48 * 1024 * 1024  # 48 MB por asset (corto, para escenas)
_UA = "edgetape-automate-clipping/1.0 (+https://github.com/haimerb/automate-clipping)"


@dataclass(frozen=True)
class Material:
    """Un asset de stock listo para descargar y montar."""

    provider: str  # "pexels" | "pixabay"
    kind: str  # "video" | "photo"
    uid: str  # id global único (para dedupe)
    url: str
    width: int
    height: int
    duration: float  # 0.0 para fotos
    landscape: bool
    page_url: str | None = None


@dataclass
class MaterialLibrary:
    """Cliente con estado: claves, caché de búsquedas y set de assets usados.

    Se instancia una vez por render y se pasa a través de las búsquedas para que
    la deduplicación funcione en todas las escenas.
    """

    pexels_keys: list[str] = field(default_factory=list)
    pixabay_keys: list[str] = field(default_factory=list)
    used: set[str] = field(default_factory=set)
    _cache: dict[tuple, list[Material]] = field(default_factory=dict)
    _rotation: dict[str, int] = field(default_factory=dict)

    # ── claves ───────────────────────────────────────────

    def _next_key(self, provider: str) -> str | None:
        keys = self.pexels_keys if provider == "pexels" else self.pixabay_keys
        if not keys:
            return None
        i = self._rotation.get(provider, 0)
        self._rotation[provider] = (i + 1) % len(keys)
        return keys[i]

    # ── búsqueda ─────────────────────────────────────────

    def search(
        self,
        query: str,
        want_landscape: bool,
        per_provider: int = 12,
        client: httpx.Client | None = None,
    ) -> list[Material]:
        """Busca en los proveedores disponibles y devuelve candidatos únicos.

        Intercala proveedores para no depender de uno solo; prioriza video.
        """
        query = " ".join(query.split())[:80]
        if not query:
            return []
        cache_key = (query.lower(), want_landscape, per_provider)
        if cache_key in self._cache:
            return self._cache[cache_key]

        own = client is None
        c = client or httpx.Client(timeout=_API_TIMEOUT, headers={"User-Agent": _UA})
        results: list[Material] = []
        try:
            providers = []
            if self.pexels_keys:
                providers.append("pexels")
            if self.pixabay_keys:
                providers.append("pixabay")
            random.shuffle(providers)

            def _query(provider: str, kind: str) -> list[Material]:
                try:
                    if provider == "pexels":
                        return self._pexels(c, query, kind, want_landscape, per_provider)
                    return self._pixabay(c, query, kind, want_landscape, per_provider)
                except Exception as exc:  # noqa: BLE001 — un proveedor no tumba al otro
                    logger.warning("stock %s/%s falló para '%s': %s", provider, kind, query, exc)
                    return []

            for provider in providers:
                results += _query(provider, "video")
            if not results and os.environ.get("EDGETAPE_STOCK_PHOTOS", "1") != "0":
                for provider in providers:
                    results += _query(provider, "photo")
        finally:
            if own:
                c.close()

        # video primero, luego fotos; dedupe por uid
        seen: set[str] = set()
        unique: list[Material] = []
        for m in sorted(results, key=lambda x: 0 if x.kind == "video" else 1):
            if m.uid in seen:
                continue
            seen.add(m.uid)
            unique.append(m)
        self._cache[cache_key] = unique
        return unique

    def take(self, candidates: list[Material]) -> Material | None:
        """Devuelve el primer candidato no usado y lo marca como usado."""
        for m in candidates:
            if m.uid not in self.used:
                self.used.add(m.uid)
                return m
        return None

    # ── proveedores ──────────────────────────────────────

    def _pexels(
        self, client: httpx.Client, query: str, kind: str, want_landscape: bool, n: int
    ) -> list[Material]:
        key = self._next_key("pexels")
        if not key:
            return []
        orientation = "landscape" if want_landscape else "portrait"
        target_w = 1920 if want_landscape else 1080
        headers = {"Authorization": key}
        if kind == "video":
            resp = client.get(
                PEXELS_VIDEO_URL,
                params={"query": query, "orientation": orientation, "per_page": n, "size": "medium"},
                headers=headers,
            )
            resp.raise_for_status()
            out: list[Material] = []
            for v in resp.json().get("videos", []):
                files = [f for f in (v.get("video_files") or []) if f.get("file_type") == "video/mp4"]
                if not files:
                    continue
                files.sort(key=lambda f: abs((f.get("width") or 0) - target_w))
                best = next((f for f in files if (f.get("width") or 0) >= 960), files[0])
                if not best.get("link"):
                    continue
                out.append(
                    Material(
                        provider="pexels",
                        kind="video",
                        uid=f"pexels-v-{v.get('id')}",
                        url=best["link"],
                        width=int(best.get("width") or v.get("width") or 0),
                        height=int(best.get("height") or v.get("height") or 0),
                        duration=float(v.get("duration") or 0),
                        landscape=(int(v.get("width") or 0) >= int(v.get("height") or 1)),
                        page_url=v.get("url"),
                    )
                )
            return out
        resp = client.get(
            PEXELS_PHOTO_URL,
            params={"query": query, "orientation": orientation, "per_page": n},
            headers=headers,
        )
        resp.raise_for_status()
        out = []
        for p in resp.json().get("photos", []):
            src = p.get("src") or {}
            url = src.get("large2x") or src.get("large") or src.get("original")
            if not url:
                continue
            out.append(
                Material(
                    provider="pexels",
                    kind="photo",
                    uid=f"pexels-p-{p.get('id')}",
                    url=url,
                    width=int(p.get("width") or 0),
                    height=int(p.get("height") or 0),
                    duration=0.0,
                    landscape=(int(p.get("width") or 0) >= int(p.get("height") or 1)),
                    page_url=p.get("url"),
                )
            )
        return out

    def _pixabay(
        self, client: httpx.Client, query: str, kind: str, want_landscape: bool, n: int
    ) -> list[Material]:
        key = self._next_key("pixabay")
        if not key:
            return []
        orientation = "horizontal" if want_landscape else "vertical"
        safe = "true"
        if kind == "video":
            resp = client.get(
                PIXABAY_VIDEO_URL,
                params={
                    "key": key, "q": query, "per_page": max(3, min(n, 20)),
                    "video_type": "film", "safesearch": safe,
                },
            )
            resp.raise_for_status()
            out: list[Material] = []
            for v in resp.json().get("hits", []):
                if v.get("width") and (v["width"] > v.get("height", 1)) != want_landscape:
                    continue
                videos = v.get("videos") or {}
                variant = videos.get("large") or videos.get("medium") or videos.get("small")
                if not variant or not variant.get("url"):
                    continue
                out.append(
                    Material(
                        provider="pixabay",
                        kind="video",
                        uid=f"pixabay-v-{v.get('id')}",
                        url=variant["url"],
                        width=int(variant.get("width") or 0),
                        height=int(variant.get("height") or 0),
                        duration=float(v.get("duration") or 0),
                        landscape=bool(want_landscape),
                        page_url=v.get("pageURL"),
                    )
                )
            return out
        resp = client.get(
            PIXABAY_PHOTO_URL,
            params={
                "key": key, "q": query, "image_type": "photo", "orientation": orientation,
                "per_page": max(3, min(n, 20)), "safesearch": safe,
            },
        )
        resp.raise_for_status()
        out = []
        for p in resp.json().get("hits", []):
            url = p.get("largeImageURL") or p.get("webformatURL")
            if not url:
                continue
            out.append(
                Material(
                    provider="pixabay",
                    kind="photo",
                    uid=f"pixabay-p-{p.get('id')}",
                    url=url,
                    width=int(p.get("imageWidth") or 0),
                    height=int(p.get("imageHeight") or 0),
                    duration=0.0,
                    landscape=(int(p.get("imageWidth") or 0) >= int(p.get("imageHeight") or 1)),
                    page_url=p.get("pageURL"),
                )
            )
        return out


# ── helpers de módulo ─────────────────────────────────────────


def _split_keys(env: str) -> list[str]:
    return [k.strip() for k in os.environ.get(env, "").split(",") if k.strip()]


def enabled() -> bool:
    """¿Hay material de stock configurado y habilitado?"""
    if os.environ.get("EDGETAPE_AI_IMAGES", "1") == "0":
        return False
    if os.environ.get("EDGETAPE_STOCK_MATERIALS", "1") == "0":
        return False
    return bool(_split_keys("EDGETAPE_PEXELS_API_KEY") or _split_keys("EDGETAPE_PIXABAY_API_KEY"))


def build_library() -> MaterialLibrary | None:
    """Crea la librería si hay claves; None si el stock está desactivado."""
    if not enabled():
        return None
    return MaterialLibrary(
        pexels_keys=_split_keys("EDGETAPE_PEXELS_API_KEY"),
        pixabay_keys=_split_keys("EDGETAPE_PIXABAY_API_KEY"),
    )


def download(client: httpx.Client, material: Material, dest: Path) -> bool:
    """Descarga un asset a `dest` (sin extensión). Devuelve True si quedó válido."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", material.url, timeout=_DOWNLOAD_TIMEOUT) as resp:
            resp.raise_for_status()
            size = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_DOWNLOAD_BYTES:
                        logger.warning("asset %s excede el tope de descarga; descartado", material.uid)
                        fh.close()
                        dest.unlink(missing_ok=True)
                        return False
                    fh.write(chunk)
        if not dest.exists() or dest.stat().st_size < 2048:
            dest.unlink(missing_ok=True)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("descarga de %s falló: %s", material.uid, exc)
        dest.unlink(missing_ok=True)
        return False
