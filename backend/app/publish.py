from __future__ import annotations

import logging

from sqlalchemy import select

from . import youtube_publish as yt
from .db import SessionLocal
from .models import Clip, Job, PlatformPost
from .processing import export_clip
from .storage import JobStore
from .users import LinkedAccount

logger = logging.getLogger(__name__)

STUDIO_UPLOAD_URL = "https://www.youtube.com/upload"

PUBLISHED_STATUSES = {"publicado", "listo"}


def _job_description(clip: Clip) -> str:
    text = clip.script.strip() or clip.line.strip()
    return (
        f"Clip extraído con edgetape.\n\n{text}\n\n"
        "#shorts #clip #edicion"
    )


def _youtube_account(store: JobStore, job: Job, account: str | None) -> LinkedAccount | None:
    db = SessionLocal()
    try:
        q = select(LinkedAccount).where(LinkedAccount.user_id == job.owner_id)
        if account:
            q = q.where(LinkedAccount.name == account)
        else:
            q = q.where(LinkedAccount.platform == "youtube")
            return db.scalar(q.order_by(LinkedAccount.created_at))
        return db.scalar(q.limit(1))
    finally:
        db.close()


def _already_published(store: JobStore, job_id: str, clip_id: str, platform: str) -> bool:
    return any(
        p.clip_id == clip_id and p.platform == platform and p.status in PUBLISHED_STATUSES
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
    if _already_published(store, job.id, clip.id, platform):
        return None

    if not (clip.exported and clip.export_name):
        clip = await export_clip(job.id, clip.id, store)
        if clip is None:
            return None
    path = store.exports_dir(job.id) / clip.export_name
    if not path.exists():
        return None

    linked = _youtube_account(store, job, account)
    token = (linked.token if linked else None) or ""
    creds = yt.creds_for(linked)

    if token and _is_refresh_token(token) and creds is not None:
        try:
            video = await yt.upload_video(
                str(path), clip.title, _job_description(clip), token, creds
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("subida a YouTube falló (%s); usando respaldo", exc)
            video = None
        if video:
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
        url=STUDIO_UPLOAD_URL,
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


async def auto_publish_clip(store: JobStore, job_id: str, clip_id: str) -> None:
    """Publicación automática de un clip recién marcado cuando el job tiene
    auto_publish activado."""
    job = store.get_job(job_id)
    if job is None or not job.auto_publish or job.status != "done":
        return
    clip = next((c for c in store.get_clips(job_id) if c.id == clip_id), None)
    if clip is None or not clip.publish:
        return
    try:
        await publish_one(store, job, clip)
    except Exception as exc:  # noqa: BLE001
        logger.warning("publicación automática falló para %s: %s", clip_id, exc)
