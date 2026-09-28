from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
FINALIZE_URL = "https://open.tiktokapis.com/v2/post/publish/video/finalize/"
DEFAULT_REDIRECT = "http://localhost:8000/api/tiktok/callback"
DEFAULT_SCOPE = "video.upload,video.publish"


@dataclass(frozen=True)
class TiktokCreds:
    """Credenciales de la app de TikTok (Content Posting API). Pueden venir de la
    cuenta vinculada (columnas client_id/client_secret) o del entorno."""

    client_key: str
    client_secret: str
    redirect_uri: str


def _env_client_key() -> str | None:
    return os.environ.get("EDGETAPE_TIKTOK_CLIENT_KEY")


def _env_client_secret() -> str | None:
    return os.environ.get("EDGETAPE_TIKTOK_CLIENT_SECRET")


def default_redirect_uri() -> str:
    return os.environ.get("EDGETAPE_TIKTOK_REDIRECT_URI") or DEFAULT_REDIRECT


def creds_for(account=None, redirect_uri: str | None = None) -> TiktokCreds | None:
    """Devuelve credenciales para subir a TikTok, priorizando las de la cuenta."""
    default = default_redirect_uri()
    if account is not None:
        key = getattr(account, "client_id", None)
        secret = getattr(account, "client_secret", None)
        if key and secret:
            uri = getattr(account, "redirect_uri", None) or redirect_uri or default
            return TiktokCreds(key, secret, uri)
    key = _env_client_key()
    secret = _env_client_secret()
    if key and secret:
        return TiktokCreds(key, secret, redirect_uri or default)
    return None


def is_configured(account=None) -> bool:
    return creds_for(account) is not None


def auth_url(state: str, creds: TiktokCreds) -> str:
    params = {
        "client_key": creds.client_key,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "redirect_uri": creds.redirect_uri,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(
    code: str, creds: TiktokCreds, client: httpx.Client | None = None
) -> dict:
    """Intercambia el código por access_token + refresh_token (la app guarda el
    refresh_token; expira a los 365 días)."""
    data = {
        "client_key": creds.client_key,
        "client_secret": creds.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": creds.redirect_uri,
    }
    own = client is None
    c = client or httpx.Client(timeout=30.0)
    try:
        resp = c.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()
    finally:
        if own:
            c.close()


def _access_token(refresh_token: str, creds: TiktokCreds, client: httpx.Client | None = None) -> str:
    data = {
        "client_key": creds.client_key,
        "client_secret": creds.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    own = client is None
    c = client or httpx.Client(timeout=30.0)
    try:
        resp = c.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()["access_token"]
    finally:
        if own:
            c.close()


def _init_upload(
    path: str, access_token: str, creds: TiktokCreds, client: httpx.Client
) -> dict:
    size = os.path.getsize(path)
    chunk_size = min(max(size, 1), 64 * 1024 * 1024)
    total_chunks = max(1, math.ceil(size / chunk_size))
    body = {
        "post_info": {
            "title": "",
            "privacy_level": "SELF_ONLY",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }
    resp = client.post(
        INIT_URL,
        json=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
    )
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    if not data.get("publish_id") or not data.get("upload_url"):
        raise RuntimeError(f"TikTok init falló: {resp.text[:500]}")
    return {
        "publish_id": data["publish_id"],
        "upload_url": data["upload_url"],
        "chunk_size": int(data.get("chunk_size") or chunk_size),
        "total_chunk_count": int(data.get("total_chunk_count") or total_chunks),
    }


def _upload_chunks(upload_url: str, path: str, chunk_size: int, client: httpx.Client) -> None:
    if chunk_size <= 0:
        chunk_size = 64 * 1024 * 1024
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            resp = client.put(upload_url, content=chunk, headers={"Content-Type": "video/mp4"})
            resp.raise_for_status()


def _finalize(
    publish_id: str,
    chunk_size: int,
    total_chunk_count: int,
    access_token: str,
    client: httpx.Client,
) -> str:
    body = {
        "publish_id": publish_id,
        "chunk_size": chunk_size,
        "total_chunk_count": total_chunk_count,
    }
    resp = client.post(
        FINALIZE_URL,
        json=body,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
    )
    resp.raise_for_status()
    data = resp.json()
    # data["data"] -> dict con status ("PUBLISH_COMPLETE" si ya quedó listo)
    return ((data.get("data") or {}).get("status") or "").upper()


def _upload_sync(
    path: str,
    title: str,
    description: str,
    refresh_token: str,
    creds: TiktokCreds,
    client: httpx.Client | None = None,
) -> dict:
    token = _access_token(refresh_token, creds, client)
    own = client is None
    c = client or httpx.Client(timeout=120.0)
    try:
        init = _init_upload(path, token, creds, c)
        _upload_chunks(init["upload_url"], path, init["chunk_size"], c)
        status = _finalize(
            init["publish_id"], init["chunk_size"], init["total_chunk_count"], token, c
        )
    finally:
        if own:
            c.close()
    return {
        "publish_id": init["publish_id"],
        "status": status,
        "url": None,
    }


async def upload_video(
    path: str,
    title: str,
    description: str,
    refresh_token: str,
    creds: TiktokCreds,
    client: httpx.Client | None = None,
) -> dict:
    """Sube un video a TikTok vía Content Posting API. Devuelve {publish_id, status, url}."""
    return await asyncio.to_thread(
        _upload_sync, path, title, description, refresh_token, creds, client
    )