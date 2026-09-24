from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from . import youtube_publish as yt
from .db import SessionLocal
from .media import extract_best_thumbnail
from .models import Clip, Job, PlatformPost
from .processing import export_clip
from .publish_queue import get_queue_manager, UploadTask
from .storage import JobStore
from .users import LinkedAccount

logger = logging.getLogger(__name__)

STUDIO_UPLOAD_URL = "https://www.youtube.com/upload"

PLATFORM_UPLOAD_URLS = {
    "youtube_shorts": STUDIO_UPLOAD_URL,
    "youtube": STUDIO_UPLOAD_URL,
    "tiktok": "https://www.tiktok.com/upload",
    "facebook_reels": "https://www.facebook.com/reels/create",
    "instagram_reels": "https://www.instagram.com/reels/create",
    "otros": None,
}

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
    if clip.thumbnail:
        p = store.exports_dir(job.id) / clip.thumbnail
        if p.exists():
            return p
        p2 = store.job_dir(job.id) / "thumbs" / clip.thumbnail
        if p2.exists():
            return p2
    for pattern in [f"{clip.id}_thumb.jpg", f"{clip.id}_thumb_0.jpg"]:
        for d in [store.exports_dir(job.id), store.job_dir(job.id) / "thumbs"]:
            p = d / pattern
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
    return token.startswith("1//")


async def publish_one(
    store: JobStore,
    job: Job,
    clip: Clip,
    platform: str = "youtube_shorts",
    account: str | None = None,
) -> PlatformPost | None:
    if _already_published(store, job.id, clip.id, platform, account):
        return None

    from .scorer import _limits_for

    max_duration = _limits_for(platform)[1]
    clip = await export_clip(job.id, clip.id, store, max_duration=max_duration)
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
                logger.info("subiendo miniatura a YouTube: %s", thumb_path)
                ok = await yt.set_thumbnail(video["id"], str(thumb_path), token, creds)
                if ok:
                    logger.info("miniatura subida exitosamente a YouTube para %s", video["id"])
                else:
                    logger.warning("no se pudo subir miniatura a YouTube para %s", video["id"])
            else:
                logger.warning("no se encontró miniatura para clip %s", clip.id)
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
    qm = get_queue_manager(store)

    from .db import SessionLocal
    from .users import LinkedAccount
    from sqlalchemy import select

    db = SessionLocal()
    try:
        linked_accounts = db.scalars(select(LinkedAccount).where(
            LinkedAccount.user_id == job.owner_id,
            LinkedAccount.platform == PLATFORM_ACCOUNT_MAP.get(platform, "otros")
        )).all()
    finally:
        db.close()

    marked = [c for c in store.get_clips(job.id) if c.publish]
    tasks = []
    for clip in marked:
        target_account = account
        if not target_account:
            best = qm.get_best_account(platform, linked_accounts)
            target_account = best.name if best else None

        if not target_account:
            store.create_post(job.id, clip.id, platform=platform, status="listo",
                            url=PLATFORM_UPLOAD_URLS.get(platform), method="manual")
            continue

        task = UploadTask(
            job_id=job.id,
            clip_id=clip.id,
            platform=platform,
            account_name=target_account,
            priority=clip.index,
        )
        tasks.append(task)

    if tasks:
        qm.enqueue_many(tasks)

    # In test mode (inproc), process synchronously
    import os
    if os.environ.get("EDGETAPE_ASYNC_BACKEND") == "inproc":
        async def _get_accounts():
            return linked_accounts
        await qm.process_queue(store, publish_one, _get_accounts)
        # Return the created posts
        created_posts = []
        for clip in marked:
            posts = store.get_posts(job.id)
            for p in posts:
                if p.clip_id == clip.id and p.platform == platform:
                    created_posts.append(p)
        return created_posts

    async def _process():
        async def _get_accounts():
            return linked_accounts
        await qm.process_queue(store, publish_one, _get_accounts)

    asyncio.create_task(_process())

    return []


async def auto_publish_clip(
    store: JobStore, job_id: str, clip_id: str,
    platform: str = "youtube_shorts", account: str | None = None,
) -> None:
    job = store.get_job(job_id)
    if job is None or not job.auto_publish or job.status != "done":
        return
    clip = next((c for c in store.get_clips(job_id) if c.id == clip_id), None)
    if clip is None or not clip.publish:
        return

    qm = get_queue_manager(store)

    from .db import SessionLocal
    from .users import LinkedAccount
    from sqlalchemy import select

    db = SessionLocal()
    try:
        linked_accounts = db.scalars(select(LinkedAccount).where(
            LinkedAccount.user_id == job.owner_id,
            LinkedAccount.platform == PLATFORM_ACCOUNT_MAP.get(platform, "otros")
        )).all()
    finally:
        db.close()

    target_account = account
    if not target_account:
        best = qm.get_best_account(platform, linked_accounts)
        target_account = best.name if best else None

    if not target_account:
        store.create_post(job.id, clip.id, platform=platform, status="listo",
                        url=PLATFORM_UPLOAD_URLS.get(platform), method="manual")
        return

    task = UploadTask(
        job_id=job_id,
        clip_id=clip_id,
        platform=platform,
        account_name=target_account,
        priority=clip.index,
    )
    qm.enqueue(task)

    async def _process():
        async def _get_accounts():
            return linked_accounts
        await qm.process_queue(store, publish_one, _get_accounts)

    await _process()