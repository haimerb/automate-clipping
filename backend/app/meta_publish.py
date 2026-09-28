from __future__ import annotations

import asyncio
import logging
import os
import time
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"
API_VERSION = "v21.0"
MAX_CHUNK = 8 * 1024 * 1024
_POLL_RETRIES = 12
_POLL_DELAY = 2.0


def _node_url(node: str, extra: str = "") -> str:
    return f"{GRAPH_URL}/{API_VERSION}/{node}{extra}"


def _publish_facebook_sync(
    page_id: str,
    page_token: str,
    path: str,
    title: str,
    description: str,
    client: httpx.Client | None = None,
) -> dict:
    """Publica un video en una página de Facebook usando Graph Resumable Upload."""
    size = os.path.getsize(path)
    own = client is None
    c = client or httpx.Client(timeout=120.0)
    try:
        params = {
            "upload_phase": "start",
            "file_size": str(size),
            "access_token": page_token,
        }
        start = c.post(_node_url(page_id, "/videos"), params=params)
        start.raise_for_status()
        start_data = start.json()
        session = start_data.get("upload_session_id")
        if not session:
            raise RuntimeError(f"Facebook upload start falló: {start.text[:500]}")
        chunk_size = int(start_data.get("video_file_chunk_size") or MAX_CHUNK)

        offset = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                step = c.post(
                    _node_url(page_id, "/videos"),
                    params={
                        "upload_phase": "transfer",
                        "upload_session_id": session,
                        "start_offset": str(offset),
                        "access_token": page_token,
                    },
                    files={"video_file_chunk": ("chunk", chunk, "video/mp4")},
                )
                step.raise_for_status()
                offset += len(chunk)

        finish = c.post(
            _node_url(page_id, "/videos"),
            params={
                "upload_phase": "finish",
                "upload_session_id": session,
                "access_token": page_token,
                "title": title[:100],
                "description": description[:5000],
            },
        )
        finish.raise_for_status()
        video_id = (finish.json() or {}).get("video_id")
        if not video_id:
            raise RuntimeError(f"Facebook upload finish falló: {finish.text[:500]}")
        return {"id": video_id, "url": f"https://www.facebook.com/watch/?v={video_id}"}
    finally:
        if own:
            c.close()


async def publish_to_facebook(
    page_id: str,
    page_token: str,
    path: str,
    title: str,
    description: str,
    client: httpx.Client | None = None,
) -> dict:
    """Publica un video en una página de Facebook. Devuelve {id, url}."""
    return await asyncio.to_thread(
        _publish_facebook_sync, page_id, page_token, path, title, description, client
    )


def _create_reel_container_sync(
    ig_user_id: str,
    access_token: str,
    video_url: str,
    caption: str,
    client: httpx.Client,
) -> str:
    body = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
        "access_token": access_token,
    }
    resp = client.post(_node_url(ig_user_id, "/media"), params=body)
    resp.raise_for_status()
    container_id = (resp.json() or {}).get("id")
    if not container_id:
        raise RuntimeError(f"Instagram container falló: {resp.text[:500]}")
    return str(container_id)


def _poll_container_sync(
    container_id: str, access_token: str, client: httpx.Client
) -> str:
    url = _node_url(container_id)
    for _ in range(_POLL_RETRIES):
        resp = client.get(
            url,
            params={"fields": "status_code,permalink,id", "access_token": access_token},
        )
        resp.raise_for_status()
        status = ((resp.json() or {}).get("status_code") or "").upper()
        if status == "FINISHED":
            return str((resp.json() or {}).get("id") or container_id)
        if status == "ERROR":
            raise RuntimeError(f"Instagram container en ERROR: {resp.text[:500]}")
        time.sleep(_POLL_DELAY)
    raise RuntimeError("Instagram container no terminó de procesarse (timeout)")


def _publish_instagram_sync(
    ig_user_id: str,
    access_token: str,
    video_url: str | None,
    caption: str,
    client: httpx.Client | None = None,
) -> dict | None:
    """Publica un Reel de Instagram. El archivo debe estar en una URL pública
    accesible por los servidores de Meta; sin `video_url` no se puede iterar, así
    que devuelve None (el caller cae al respaldo manual)."""
    if not video_url:
        return None
    own = client is None
    c = client or httpx.Client(timeout=120.0)
    try:
        container_id = _create_reel_container_sync(ig_user_id, access_token, video_url, caption, c)
        media_id = _poll_container_sync(container_id, access_token, c)
        publish = c.post(
            _node_url(ig_user_id, "/media_publish"),
            params={"creation_id": container_id, "access_token": access_token},
        )
        publish.raise_for_status()
        shortcode = (publish.json() or {}).get("id") or media_id
        return {
            "id": str(media_id),
            "shortcode": str(shortcode),
            "url": f"https://www.instagram.com/reel/{urllib.parse.quote(str(shortcode))}/",
        }
    finally:
        if own:
            c.close()


async def publish_to_instagram(
    ig_user_id: str,
    access_token: str,
    video_url: str | None,
    caption: str,
    client: httpx.Client | None = None,
) -> dict | None:
    """Publica un Reel de Instagram. Devuelve {id, shortcode, url} o None si falta
    la URL pública del video."""
    return await asyncio.to_thread(
        _publish_instagram_sync, ig_user_id, access_token, video_url, caption, client
    )