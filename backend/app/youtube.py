from __future__ import annotations

import asyncio
import os
from pathlib import Path

YT_DOMAINS = ("youtube.com", "youtu.be")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SKIP_SUFFIXES = {".part", ".ytdl", ".json", ".description", ".info.json"}

# Perfiles de cliente YouTube de menor a mayor probabilidad de ser bloqueados.
# android/tv/web_safari suelen evitar el "PO token" que causa HTTP 403.
_CLIENT_PROFILES = [
    {"youtube": {"player_client": ["android_vr", "tv", "web_safari"]}},
    {"youtube": {"player_client": ["android", "ios"]}},
    {},  # por defecto: yt-dlp decide (incluye PO token si hay runtime JS)
]


def is_youtube_url(url: str) -> bool:
    return any(domain in url for domain in YT_DOMAINS)


def _build_opts(dest: Path) -> dict:
    opts = {
        "format": "bv*+ba/b",
        "outtmpl": str(dest) + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "merge_output_format": "mp4",
        "http_headers": {"User-Agent": _BROWSER_UA},
    }
    cookies = os.environ.get("EDGETAPE_YT_COOKIES")
    if cookies and Path(cookies).exists():
        opts["cookiefile"] = cookies
    return opts


def _download_attempt(url: str, dest: Path, extractor_args: dict) -> tuple[str, str | None]:
    import yt_dlp

    for stale in dest.parent.glob(dest.name + "*"):
        if stale.is_file():
            stale.unlink()

    opts = _build_opts(dest)
    if extractor_args:
        opts["extractor_args"] = extractor_args
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    matches = [
        p
        for p in dest.parent.glob(dest.name + ".*")
        if p.suffix not in _SKIP_SUFFIXES and not p.name.endswith(".part")
    ]
    if not matches:
        raise RuntimeError(f"No se pudo descargar el video: {url}")
    final = max(matches, key=lambda p: p.stat().st_size)
    return str(final), info.get("title")


async def download_youtube(url: str, dest: Path) -> tuple[str, str | None]:
    """Download a YouTube video to `dest` (path without extension).

    Reintenta con distintos player clients si YouTube bloquea la descarga
    (HTTP 403). yt-dlp se importa de forma perezosa.
    """
    last_error: Exception | None = None
    for profile in _CLIENT_PROFILES:
        try:
            return await asyncio.to_thread(_download_attempt, url, dest, profile)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"No se pudo descargar el video ({url}): {last_error}")
