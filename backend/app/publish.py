from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from sqlalchemy import select

from . import youtube_publish as yt
from .db import SessionLocal
from .media import extract_best_thumbnail
from .models import Clip, Job, PlatformPost
from .processing import export_clip
from .storage import JobStore
from .users import LinkedAccount

logger = logging.getLogger(__name__)

STUDIO_UPLOAD_URL = "https://www.youtube.com/upload"

# Enlace directo de subida por plataforma. Solo YouTube intenta subir por API
# (con refresh token + credenciales OAuth); el resto usa el respaldo con enlace.
PLATFORM_UPLOAD_URLS = {
    "youtube_shorts": STUDIO_UPLOAD_URL,
    "youtube": STUDIO_UPLOAD_URL,
    "tiktok": "https://www.tiktok.com/upload",
    "facebook_reels": "https://www.facebook.com/reels/create",
    "instagram_reels": "https://www.instagram.com/reels/create",
    "otros": None,
}

# platform de publicación -> platform de la cuenta vinculada asociada
PLATFORM_ACCOUNT_MAP = {
    "youtube_shorts": "youtube",
    "youtube": "youtube",
    "tiktok": "tiktok",
    "facebook_reels": "facebook",
    "instagram_reels": "instagram",
    "otros": "otros",
}

PUBLISHED_STATUSES = {"publicado"}


def _resolve_thumbnail(store: JobStore, job: Job, clip: Clip) -> Path | None:
    """Devuelve la ruta a la miniatura del clip. Si no existe, la genera on-the-fly."""
    if clip.thumbnail:
        p = store.exports_dir(job.id) / clip.thumbnail
        if p.exists():
            return p
    source = store.source_path(job.id)
    if not source.exists():
        return None
    try:
        out = store.exports_dir(job.id) / f"{clip.id}_thumb.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        extract_best_thumbnail(source, clip.start, clip.end, out)
        return out if out.exists() else None
    except Exception:
        return None


def _job_description(clip: Clip) -> str:
    if clip.description:
        return clip.description
    text = clip.script.strip() or clip.line.strip()
    tags = " ".join(f"#{t}" for t in clip.tags[:8]) if clip.tags else "#shorts #clip #viral"
    return f"{text[:300]}\n\n{tags}"


def _platform_account(
    store: JobStore, job: Job, platform: str, account: str | None
) -> LinkedAccount | None:
    """Resuelve la cuenta vinculada para el destino (plataforma + nombre de cuenta)."""
    platform_key = PLATFORM_ACCOUNT_MAP.get(platform, "otros")
    db = SessionLocal()
    try:
        q = select(LinkedAccount).where(
            LinkedAccount.user_id == job.owner_id,
            LinkedAccount.platform == platform_key,
        )
        if account:
            return db.scalar(q.where(LinkedAccount.name == account).limit(1))
        return db.scalar(q.order_by(LinkedAccount.created_at))
    finally:
        db.close()


def _already_published(
    store: JobStore, job_id: str, clip_id: str, platform: str, account: str | None = None
) -> bool:
    return any(
        p.clip_id == clip_id
        and p.platform == platform
        and p.account == account
        and p.status in PUBLISHED_STATUSES
        for p in store.get_posts(job_id)
    )


def _is_refresh_token(token: str) -> bool:
    """Los refresh tokens de Google empiezan por '1//'. Las API keys (AIzaSy…)
    nunca pueden subir videos, así que se tratan como no conectado."""
    return token.startswith("1//")


async def publish_one(
    store: JobStore,
    job: Job,
    clip: Clip,
    platform: str = "youtube_shorts",
    account: str | None = None,
) -> PlatformPost | None:
    """Publica un clip: exporta el archivo y, si hay credenciales de YouTube,
    lo sube de verdad vía la API. Si no, deja un post 'listo' con el enlace
    directo para subirlo a YouTube Studio."""
    if _already_published(store, job.id, clip.id, platform, account):
        return None

    if not (clip.exported and clip.export_name):
        clip = await export_clip(job.id, clip.id, store)
        if clip is None:
            return None
    path = store.exports_dir(job.id) / clip.export_name
    if not path.exists():
        return None

    linked = _platform_account(store, job, platform, account)
    token = (linked.token if linked else None) or ""
    creds = yt.creds_for(linked)

    is_youtube = platform in ("youtube_shorts", "youtube")
    if is_youtube and token and _is_refresh_token(token) and creds is not None:
        try:
            video = await yt.upload_video(
                str(path), clip.title, _job_description(clip), token, creds,
                tags=clip.tags[:15] if clip.tags else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("subida a YouTube falló (%s); usando respaldo", exc)
            video = None
        if video:
            thumb_path = _resolve_thumbnail(store, job, clip)
            if thumb_path is not None:
                try:
                    await yt.set_thumbnail(video["id"], str(thumb_path), token, creds)
                except Exception:
                    pass
            return store.create_post(
                job.id, clip.id,
                platform=platform,
                status="publicado",
                url=video["url"],
                method="youtube_api",
                account=linked.name if linked else None,
            )

    return store.create_post(
        job.id, clip.id,
        platform=platform,
        status="listo",
        url=PLATFORM_UPLOAD_URLS.get(platform),
        method="manual",
        account=linked.name if linked else None,
    )


async def publish_all(
    store: JobStore, job: Job, platform: str = "youtube_shorts", account: str | None = None
) -> list[PlatformPost]:
    """Publica todos los clips marcados (flag publish) del job."""
    created: list[PlatformPost] = []
    for clip in store.get_clips(job.id):
        if not clip.publish:
            continue
        try:
            post = await publish_one(store, job, clip, platform, account)
        except Exception as exc:  # noqa: BLE001
            logger.warning("no se pudo publicar el clip %s: %s", clip.id, exc)
            post = None
        if post is not None:
            created.append(post)
    return created


async def auto_publish_clip(
    store: JobStore, job_id: str, clip_id: str,
    platform: str = "youtube_shorts", account: str | None = None,
) -> None:
    """Publicación automática de un clip recién marcado cuando el job tiene
    auto_publish activado."""
    job = store.get_job(job_id)
    if job is None or not job.auto_publish or job.status != "done":
        return
    clip = next((c for c in store.get_clips(job_id) if c.id == clip_id), None)
    if clip is None or not clip.publish:
        return
    try:
        await publish_one(store, job, clip, platform=platform, account=account)
    except Exception as exc:  # noqa: BLE001
        logger.warning("publicación automática falló para %s: %s", clip_id, exc)
