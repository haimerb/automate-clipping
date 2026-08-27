from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl"
DEFAULT_REDIRECT = "http://localhost:8000/api/youtube/callback"


@dataclass(frozen=True)
class Creds:
    """Credenciales OAuth de una app de Google Cloud. Pueden venir de la cuenta
    vinculada del usuario (base de datos) o de variables de entorno globales."""

    client_id: str
    client_secret: str
    redirect_uri: str


def _env_client_id() -> str | None:
    return os.environ.get("EDGETAPE_YT_CLIENT_ID")


def _env_client_secret() -> str | None:
    return os.environ.get("EDGETAPE_YT_CLIENT_SECRET")


def default_redirect_uri() -> str:
    return os.environ.get("EDGETAPE_YT_REDIRECT_URI") or DEFAULT_REDIRECT


def creds_for(account=None, redirect_uri: str | None = None) -> Creds | None:
    """Devuelve las credenciales para subir a YouTube. Prioriza las guardadas en
    la cuenta vinculada del usuario; si no las tiene, cae a las de entorno."""
    default = default_redirect_uri()
    if account is not None:
        cid = getattr(account, "client_id", None)
        csec = getattr(account, "client_secret", None)
        if cid and csec:
            uri = getattr(account, "redirect_uri", None) or redirect_uri or default
            return Creds(cid, csec, uri)
    cid = _env_client_id()
    csec = _env_client_secret()
    if cid and csec:
        return Creds(cid, csec, redirect_uri or default)
    return None


def is_configured(account=None) -> bool:
    """La subida real a YouTube requiere credenciales OAuth de Google Cloud."""
    return creds_for(account) is not None


def auth_url(state: str, creds: Creds) -> str:
    params = {
        "client_id": creds.client_id,
        "redirect_uri": creds.redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, creds: Creds, client: httpx.Client | None = None) -> str:
    """Intercambia el código de autorización por un refresh_token."""
    data = {
        "code": code,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "redirect_uri": creds.redirect_uri,
        "grant_type": "authorization_code",
    }
    own = client is None
    c = client or httpx.Client(timeout=30.0)
    try:
        resp = c.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()["refresh_token"]
    finally:
        if own:
            c.close()


def _access_token(refresh_token: str, creds: Creds, client: httpx.Client | None = None) -> str:
    data = {
        "refresh_token": refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "grant_type": "refresh_token",
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


def _metadata(title: str, description: str, tags: list[str], privacy: str) -> dict:
    return {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy},
    }


def _upload_sync(
    path: str,
    title: str,
    description: str,
    refresh_token: str,
    creds: Creds,
    privacy: str,
    tags: list[str],
    client: httpx.Client | None = None,
) -> dict:
    token = _access_token(refresh_token, creds, client)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    url = f"{UPLOAD_URL}?{urlencode({'uploadType': 'resumable', 'part': 'snippet,status'})}"
    own = client is None
    c = client or httpx.Client(timeout=60.0)
    try:
        resp = c.post(url, json=_metadata(title, description, tags, privacy), headers=headers)
        if resp.status_code >= 400:
            import logging
            logging.getLogger(__name__).error(
                "YouTube upload init failed %s\nResponse: %s\nMetadata: %s",
                resp.status_code, resp.text[:1000], _metadata(title, description, tags, privacy),
            )
            resp.raise_for_status()
        location = resp.headers["location"]
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            up = c.put(
                location,
                content=fh.read(),
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size),
                    "Authorization": f"Bearer {token}",
                },
            )
            up.raise_for_status()
        data = up.json()
    finally:
        if own:
            c.close()
    video_id = data.get("id")
    return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


async def upload_video(
    path: str,
    title: str,
    description: str,
    refresh_token: str,
    creds: Creds,
    privacy: str = "unlisted",
    tags: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Sube un video a YouTube vía resumable upload. Devuelve {id, url}."""
    return await asyncio.to_thread(
        _upload_sync, path, title, description, refresh_token, creds, privacy, tags or [], client
    )


THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


def _set_thumbnail_sync(
    video_id: str,
    thumb_path: str,
    refresh_token: str,
    creds: Creds,
    client: httpx.Client | None = None,
) -> bool:
    """Sube una miniatura custom a un video de YouTube ya existente."""
    own = client is None
    c = client or httpx.Client(timeout=60.0)
    try:
        token = _access_token(refresh_token, creds, c)
        with open(thumb_path, "rb") as fh:
            resp = c.post(
                f"{THUMBNAIL_URL}?videoId={video_id}",
                headers={"Authorization": f"Bearer {token}"},
                files={"media": ("thumb.jpg", fh, "image/jpeg")},
            )
        if resp.status_code >= 400:
            import logging
            logging.getLogger(__name__).warning(
                "YouTube thumbnail upload failed %s: %s",
                resp.status_code, resp.text[:300],
            )
            return False
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("YouTube thumbnail upload error: %s", exc)
        return False
    finally:
        if own:
            c.close()


async def set_thumbnail(
    video_id: str,
    thumb_path: str,
    refresh_token: str,
    creds: Creds,
    client: httpx.Client | None = None,
) -> bool:
    """Sube miniatura custom a YouTube (async wrapper)."""
    return await asyncio.to_thread(
        _set_thumbnail_sync, video_id, thumb_path, refresh_token, creds, client
    )
