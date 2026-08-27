from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import create_token, get_current_user, get_current_user_media, hash_password, verify_password
from .db import get_db, init_db
from . import publish as pubmod
from . import youtube_publish as ytpub
from .llm_scorer import build_clip_selector
from .media import extract_thumbnail
from .models import (
    Clip,
    ClipPublish,
    ClipUpdate,
    DashboardStats,
    GenerateRequest,
    Job,
    JobSettings,
    LinkedAccountCreate,
    LinkedAccountOut,
    LoginRequest,
    MetadataUpdate,
    PlatformPost,
    PlatformTotals,
    PostCreate,
    PublishAllRequest,
    PublishClipRequest,
    PublishResult,
    RecentPost,
    RegisterRequest,
    ThumbnailSelect,
    TokenResponse,
    UserOut,
)
from .processing import export_clip
from .storage import JobStore
from .tasks import enqueue_auto_publish, enqueue_job
from .transcriber import build_transcriber
from .users import LinkedAccount, User
from .youtube import is_youtube_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE = BACKEND_DIR / "storage"


class YoutubeRequest(BaseModel):
    url: str


def _build_dashboard(store: JobStore, owner_id: str) -> DashboardStats:
    stats = DashboardStats()
    recent: list[RecentPost] = []
    for job in store.list_jobs(owner_id):
        stats.jobs += 1
        clips = store.get_clips(job.id)
        stats.clips += len(clips)
        titles = {c.id: c.title for c in clips}
        for post in store.get_posts(job.id):
            stats.posts += 1
            if post.status == "publicado":
                stats.publicados += 1
            stats.total_views += post.views
            stats.total_likes += post.likes
            stats.total_earnings += post.earnings
            tot = stats.by_platform.setdefault(post.platform, PlatformTotals())
            tot.posts += 1
            tot.views += post.views
            tot.likes += post.likes
            tot.earnings += post.earnings
            recent.append(
                RecentPost(
                    post_id=post.id,
                    job_id=job.id,
                    clip_id=post.clip_id,
                    title=titles.get(post.clip_id, job.filename),
                    platform=post.platform,
                    status=post.status,
                    url=post.url,
                    views=post.views,
                    likes=post.likes,
                    earnings=post.earnings,
                    currency=post.currency,
                )
            )
    stats.recent_posts = sorted(recent, key=lambda r: r.post_id, reverse=True)[:20]
    return stats


def _account_out(account: LinkedAccount) -> LinkedAccountOut:
    """Serializa una cuenta vinculada sin exponer el client_secret."""
    return LinkedAccountOut(
        id=account.id,
        platform=account.platform,
        name=account.name,
        handle=account.handle,
        token=account.token,
        client_id=account.client_id,
        has_client_secret=bool(account.client_secret),
        redirect_uri=account.redirect_uri,
        created_at=account.created_at,
    )


def create_app(storage_root: str | Path | None = None, transcriber=None, selector=None) -> FastAPI:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    store = JobStore(storage_root or os.environ.get("EDGETAPE_STORAGE") or DEFAULT_STORAGE)
    tsc = transcriber or build_transcriber()
    sel = selector or build_clip_selector()
    init_db()

    app = FastAPI(title="ClipForge", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def owned_job(job_id: str, user_id: str) -> Job:
        job = store.get_job(job_id)
        if job is None or job.owner_id != user_id:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    def owned_clip(job: Job, clip_id: str) -> Clip:
        clip = next((c for c in store.get_clips(job.id) if c.id == clip_id), None)
        if clip is None:
            raise HTTPException(status_code=404, detail="clip not found")
        return clip

    @app.post("/api/jobs/{job_id}/transcription", response_model=Job)
    async def receive_transcription(
        job_id: str, request: Request
    ) -> Job:
        """Receive transcription segments from Colab or external service."""
        # Verify secret token
        secret = os.environ.get("EDGETAPE_COLAB_SECRET")
        if secret:
            auth_header = request.headers.get("Authorization", "")
            if auth_header != f"Bearer {secret}":
                raise HTTPException(status_code=401, detail="Invalid secret")

        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")

        body = await request.json()
        segments = body.get("segments", [])
        if not segments:
            raise HTTPException(status_code=400, detail="No segments provided")

        # Store transcription
        import json
        job_dir = store.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "transcription.json").write_text(
            json.dumps(segments, ensure_ascii=False), encoding="utf-8"
        )

        # Continue pipeline: scoring → metadata → export
        from .processing import run_job
        await run_job(job_id, store, tsc, sel)

        return store.get_job(job_id)

    @app.get("/api/health")
    def health() -> dict:
        try:
            import yt_dlp  # noqa: F401

            yt = True
        except ImportError:
            yt = False
        return {
            "ok": True,
            "version": app.version,
            "transcriber": tsc.name,
            "scorer": sel.name,
            "youtube": yt,
        }

    # ── auth ──────────────────────────────────────────

    @app.post("/api/auth/register", response_model=TokenResponse, status_code=201)
    def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
        email = body.email.strip().lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=422, detail="Email inválido")
        if len(body.password) < 6:
            raise HTTPException(status_code=422, detail="La contraseña debe tener al menos 6 caracteres")
        if db.scalar(select(User).where(User.email == email)) is not None:
            raise HTTPException(status_code=409, detail="Ese email ya está registrado")
        user = User(
            id=uuid.uuid4().hex,
            email=email,
            name=body.name.strip() or email.split("@")[0],
            password_hash=hash_password(body.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return TokenResponse(access_token=create_token(user), user=UserOut(**user.__dict__))

    @app.post("/api/auth/login", response_model=TokenResponse)
    def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
        email = body.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
        return TokenResponse(access_token=create_token(user), user=UserOut(**user.__dict__))

    @app.get("/api/auth/me", response_model=UserOut)
    def me(user: User = Depends(get_current_user)) -> UserOut:
        return UserOut(**user.__dict__)

    # ── cuentas vinculadas ────────────────────────────

    @app.get("/api/accounts", response_model=list[LinkedAccountOut])
    def list_accounts(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> list[LinkedAccountOut]:
        accounts = db.scalars(
            select(LinkedAccount)
            .where(LinkedAccount.user_id == user.id)
            .order_by(LinkedAccount.created_at)
        )
        return [_account_out(a) for a in accounts]

    @app.post("/api/accounts", response_model=LinkedAccountOut, status_code=201)
    def create_account(
        body: LinkedAccountCreate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> LinkedAccountOut:
        account = LinkedAccount(
            id=uuid.uuid4().hex,
            user_id=user.id,
            platform=body.platform,
            name=body.name.strip(),
            handle=body.handle.strip(),
            token=(body.token or "").strip() or None,
            client_id=(body.client_id or "").strip() or None,
            client_secret=(body.client_secret or "").strip() or None,
            redirect_uri=(body.redirect_uri or "").strip() or None,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return _account_out(account)

    @app.patch("/api/accounts/{account_id}", response_model=LinkedAccountOut)
    def update_account(
        account_id: str,
        body: LinkedAccountCreate,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> LinkedAccountOut:
        account = db.scalar(
            select(LinkedAccount).where(
                LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
            )
        )
        if account is None:
            raise HTTPException(status_code=404, detail="cuenta no encontrada")
        account.platform = body.platform
        account.name = body.name.strip()
        account.handle = body.handle.strip()
        account.token = (body.token or "").strip() or None
        account.client_id = (body.client_id or "").strip() or None
        if body.client_secret:  # vacío = conservar el guardado
            account.client_secret = body.client_secret.strip()
        account.redirect_uri = (body.redirect_uri or "").strip() or None
        db.commit()
        db.refresh(account)
        return _account_out(account)

    @app.delete("/api/accounts/{account_id}", status_code=204)
    def delete_account(
        account_id: str,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> None:
        account = db.scalar(
            select(LinkedAccount).where(
                LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
            )
        )
        if account is None:
            raise HTTPException(status_code=404, detail="cuenta no encontrada")
        db.delete(account)
        db.commit()

    # ── generación con IA ─────────────────────────────

    @app.post("/api/generate", status_code=202)
    async def generate_video(
        body: GenerateRequest, user: User = Depends(get_current_user)
    ) -> dict:
        if not body.prompt.strip():
            raise HTTPException(status_code=422, detail="El prompt no puede estar vacío")
        if body.duration not in [15, 30, 60]:
            raise HTTPException(status_code=422, detail="Duración debe ser 15, 30 o 60 segundos")
        job = store.create_job(
            f"IA: {body.prompt[:50]}",
            source="generate",
            source_url=None,
            owner_id=user.id,
        )
        job_dir = store.job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "prompt": body.prompt,
            "duration": body.duration,
            "style": body.style,
            "platform": body.platform,
            "voice": body.voice,
            "auto_publish": body.auto_publish,
            "account_id": body.account_id,
        }
        import json
        (job_dir / "generate_meta.json").write_text(json.dumps(meta, ensure_ascii=False))
        import os as _os
        if _os.environ.get("EDGETAPE_ASYNC_BACKEND") == "celery":
            enqueue_job(job.id, str(store.root))
        else:
            from .processing import run_job as _run
            import asyncio as _aio
            await _run(job.id, store, tsc, sel)
        return {"job_id": job.id, "status": "queued"}

    # ── publicación real en YouTube ──────────────────

    @app.get("/api/accounts/{account_id}/youtube/auth")
    def youtube_auth_url(
        account_id: str,
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> dict:
        account = db.scalar(
            select(LinkedAccount).where(
                LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
            )
        )
        if account is None:
            raise HTTPException(status_code=404, detail="cuenta no encontrada")
        if account.platform != "youtube":
            raise HTTPException(status_code=400, detail="La cuenta no es de YouTube")
        derived_uri = f"{str(request.base_url).rstrip('/')}/api/youtube/callback"
        creds = ytpub.creds_for(account, redirect_uri=derived_uri)
        if creds is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Faltan las credenciales de YouTube (client_id y client_secret). "
                    "Regístralas en el formulario de la cuenta (Google Cloud → Credenciales "
                    "de OAuth) o define EDGETAPE_YT_CLIENT_ID y EDGETAPE_YT_CLIENT_SECRET. "
                    "Sin ellas igual puedes usar el respaldo con enlace a Studio."
                ),
            )
        return {"auth_url": ytpub.auth_url(account.id, creds), "redirect_uri": creds.redirect_uri}

    @app.get("/api/youtube/callback")
    def youtube_callback(
        code: str,
        state: str,
        request: Request,
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        account = db.get(LinkedAccount, state)
        if account is None:
            return RedirectResponse("/?youtube=error", status_code=302)
        derived_uri = f"{str(request.base_url).rstrip('/')}/api/youtube/callback"
        creds = ytpub.creds_for(account, redirect_uri=derived_uri)
        if creds is None:
            return RedirectResponse("/?youtube=error", status_code=302)
        try:
            refresh_token = ytpub.exchange_code(code, creds)
        except Exception:  # noqa: BLE001
            return RedirectResponse("/?youtube=error", status_code=302)
        account.token = refresh_token
        db.commit()
        return RedirectResponse("/?youtube=connected", status_code=302)

    # ── jobs ──────────────────────────────────────────

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        file: UploadFile = File(...), user: User = Depends(get_current_user)
    ) -> Job:
        job = store.create_job(file.filename or "upload", owner_id=user.id)
        dest = store.upload_path(job.id)
        with dest.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)
        enqueue_job(job.id, str(store.root))
        return store.get_job(job.id)  # type: ignore[return-value]

    @app.post("/api/jobs/youtube", status_code=202, response_model=Job)
    async def create_youtube_job(
        body: YoutubeRequest, user: User = Depends(get_current_user)
    ) -> Job:
        if not is_youtube_url(body.url.strip()):
            raise HTTPException(status_code=400, detail="La URL no parece ser de YouTube")
        job = store.create_job(
            "video de YouTube", source="youtube", source_url=body.url.strip(), owner_id=user.id
        )
        enqueue_job(job.id, str(store.root))
        return store.get_job(job.id)  # type: ignore[return-value]

    @app.get("/api/jobs", response_model=list[Job])
    def list_jobs(user: User = Depends(get_current_user)) -> list[Job]:
        jobs = store.list_jobs(user.id)
        return sorted(jobs, key=lambda j: (j.created_at, j.filename), reverse=True)

    @app.get("/api/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, user: User = Depends(get_current_user)) -> Job:
        return owned_job(job_id, user.id)

    @app.get("/api/jobs/{job_id}/clips", response_model=list[Clip])
    def list_clips(job_id: str, user: User = Depends(get_current_user)) -> list[Clip]:
        job = owned_job(job_id, user.id)
        clips = store.get_clips(job.id)
        needs_update = any(not c.description for c in clips)
        if needs_update and clips and job.status == "done":
            from .processing import _extract_thumbnails, _infer_platform
            from .viral import build_metadata_generator, generate_clip_metadata
            gen = build_metadata_generator()
            platform = _infer_platform(job.duration or 0.0, job.source_url)
            found = [
                {"id": c.id, "script": c.script, "title": "", "line": c.line,
                 "duration": c.duration, "start": c.start, "end": c.end, "score": c.score}
                for c in clips
            ]
            found = generate_clip_metadata(gen, found, platform)
            for orig, updated in zip(clips, found):
                orig.title = updated.get("title", orig.title)
                orig.description = updated.get("description", "")
                orig.tags = updated.get("tags", [])
            source = store.source_path(job.id)
            if source.exists():
                exports = store.exports_dir(job.id)
                exports.mkdir(parents=True, exist_ok=True)
                _extract_thumbnails(source, clips, exports)
            store.save_clips(job.id, clips)
        return clips

    @app.patch("/api/jobs/{job_id}", response_model=Job)
    def patch_job_settings(
        job_id: str, body: JobSettings, user: User = Depends(get_current_user)
    ) -> Job:
        job = owned_job(job_id, user.id)
        was_auto = job.auto_publish
        job.auto_publish = body.auto_publish
        job.auto_publish_platform = body.auto_publish_platform
        job.auto_publish_account = body.auto_publish_account
        store.save_job(job)
        # Si se activa auto_publish por primera vez y el job ya está listo,
        # disparar publicación para los clips que ya estaban marcados.
        if body.auto_publish and not was_auto and job.status == "done":
            for clip in store.get_clips(job.id):
                if clip.publish:
                    enqueue_auto_publish(
                        job.id, clip.id, str(store.root),
                        body.auto_publish_platform, body.auto_publish_account,
                    )
        return job

    @app.post("/api/jobs/{job_id}/reprocess", response_model=list[Clip])
    async def reprocess_job_clips(
        job_id: str, user: User = Depends(get_current_user)
    ) -> list[Clip]:
        """Regenera metadata viral (título, descripción, tags) y miniaturas
        para los clips existentes de un job terminado."""
        from .media import extract_best_thumbnail
        from .processing import _extract_thumbnails, _infer_platform
        from .viral import build_metadata_generator, generate_clip_metadata

        job = owned_job(job_id, user.id)
        if job.status != "done":
            raise HTTPException(status_code=409, detail="Solo se pueden reprocesar jobs terminados")
        clips = store.get_clips(job.id)
        if not clips:
            raise HTTPException(status_code=404, detail="El job no tiene clips")

        metadata_gen = build_metadata_generator()
        platform = _infer_platform(job.duration or 0.0, job.source_url)
        found = [
            {
                "id": c.id,
                "script": c.script,
                "title": "",  # hint vacío para forzar generación nueva
                "line": c.line,
                "duration": c.duration,
                "start": c.start,
                "end": c.end,
                "score": c.score,
            }
            for c in clips
        ]
        found = generate_clip_metadata(metadata_gen, found, platform)

        for orig, updated in zip(clips, found):
            orig.title = updated.get("title", orig.title)
            orig.description = updated.get("description", "")
            orig.tags = updated.get("tags", [])

        source = store.source_path(job.id)
        if source.exists():
            exports = store.exports_dir(job.id)
            exports.mkdir(parents=True, exist_ok=True)
            _extract_thumbnails(source, clips, exports)

        store.save_clips(job.id, clips)
        return clips

    @app.post("/api/jobs/{job_id}/publish-all", response_model=list[PublishResult])
    async def publish_all(
        job_id: str, body: PublishAllRequest, user: User = Depends(get_current_user)
    ) -> list[PublishResult]:
        import asyncio

        job = owned_job(job_id, user.id)
        if job.status != "done":
            raise HTTPException(status_code=409, detail="El video aún no está listo para publicar")

        marked = [c for c in store.get_clips(job.id) if c.publish]
        if not marked:
            return []

        sem = asyncio.Semaphore(3)

        async def _publish_one(clip):
            async with sem:
                try:
                    post = await pubmod.publish_one(store, job, clip, body.platform, body.account)
                    if post:
                        return PublishResult(clip_id=clip.id, status="ok", post=post)
                    return PublishResult(clip_id=clip.id, status="skipped")
                except Exception as exc:  # noqa: BLE001
                    return PublishResult(clip_id=clip.id, status="error", error=str(exc))

        results = await asyncio.gather(*[_publish_one(c) for c in marked])
        return list(results)

    @app.post(
        "/api/jobs/{job_id}/clips/{clip_id}/publish", response_model=PlatformPost, status_code=201
    )
    async def publish_clip(
        job_id: str,
        clip_id: str,
        body: PublishClipRequest,
        user: User = Depends(get_current_user),
    ) -> PlatformPost:
        job = owned_job(job_id, user.id)
        if job.status != "done":
            raise HTTPException(status_code=409, detail="El video aún no está listo para publicar")
        clip = owned_clip(job, clip_id)
        post = await pubmod.publish_one(store, job, clip, body.platform, body.account)
        if post is None:
            existing = next(
                (
                    p
                    for p in store.get_posts(job.id)
                    if p.clip_id == clip_id and p.platform == body.platform
                ),
                None,
            )
            if existing is not None:
                return existing
            raise HTTPException(status_code=409, detail="El clip ya fue publicado o no se pudo publicar")
        return post

    @app.get("/api/jobs/{job_id}/clips/{clip_id}/thumb")
    def clip_thumb(
        job_id: str, clip_id: str, user: User = Depends(get_current_user_media)
    ) -> FileResponse:
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        src = store.source_path(job.id)
        if not src.exists():
            raise HTTPException(status_code=404, detail="fuente no disponible")
        thumbs = store.job_dir(job.id) / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)

        # Use selected thumbnail if available
        if clip.thumbnail:
            out = thumbs / clip.thumbnail
            if out.exists():
                return FileResponse(out, media_type="image/jpeg")

        # Fallback to clip index-based thumbnail
        out = thumbs / f"{clip.id}.jpg"
        if not out.exists():
            at = (clip.start + clip.end) / 2
            try:
                extract_thumbnail(src, at, out)
            except Exception:  # noqa: BLE001
                raise HTTPException(status_code=500, detail="no se pudo generar la miniatura")
        return FileResponse(out, media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/clips/{clip_id}/thumbs")
    def clip_thumbs(
        job_id: str, clip_id: str, user: User = Depends(get_current_user)
    ) -> dict:
        """Return available thumbnails for a clip."""
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        thumbs_dir = store.job_dir(job.id) / "thumbs"

        # Generate multiple thumbnails if not already done
        if not clip.thumbnails:
            src = store.source_path(job.id)
            if src.exists():
                from .media import extract_multiple_thumbnails
                filenames = extract_multiple_thumbnails(
                    src, clip.start, clip.end, thumbs_dir, clip.id
                )
                if filenames:
                    clip.thumbnails = filenames
                    clip.thumbnail = filenames[0]
                    store.update_clip(job.id, clip.id,
                                      thumbnails=filenames, thumbnail=filenames[0])

        thumbnails = []
        for i, fname in enumerate(clip.thumbnails):
            thumbnails.append({
                "index": i,
                "url": f"/api/jobs/{job_id}/clips/{clip_id}/thumb?name={fname}",
                "selected": i == clip.thumbnail_index,
            })

        return {"thumbnails": thumbnails, "selected_index": clip.thumbnail_index}

    @app.patch("/api/jobs/{job_id}/clips/{clip_id}/thumbnail")
    def select_thumbnail(
        job_id: str, clip_id: str, body: ThumbnailSelect, user: User = Depends(get_current_user)
    ) -> Clip:
        """Select which thumbnail to use for a clip."""
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        if body.thumbnail_index < 0 or body.thumbnail_index >= len(clip.thumbnails):
            raise HTTPException(status_code=400, detail="Índice de miniatura inválido")
        clip.thumbnail_index = body.thumbnail_index
        clip.thumbnail = clip.thumbnails[body.thumbnail_index]
        store.update_clip(job.id, clip.id,
                          thumbnail_index=body.thumbnail_index,
                          thumbnail=clip.thumbnail)
        return clip

    @app.patch("/api/jobs/{job_id}/clips/{clip_id}/metadata", response_model=Clip)
    def update_clip_metadata(
        job_id: str, clip_id: str, body: MetadataUpdate, user: User = Depends(get_current_user)
    ) -> Clip:
        """Update title, description, and tags for a clip."""
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        updates = {}
        if body.title is not None:
            updates["title"] = body.title[:100]
        if body.description is not None:
            updates["description"] = body.description[:2000]
        if body.tags is not None:
            updates["tags"] = [t.lower().strip() for t in body.tags][:15]
        if updates:
            store.update_clip(job.id, clip_id, **updates)
            clip = owned_clip(job, clip_id)
        return clip

    @app.patch("/api/jobs/{job_id}/clips/{clip_id}", response_model=Clip)
    def set_clip_publish(
        job_id: str, clip_id: str, body: ClipUpdate, user: User = Depends(get_current_user)
    ) -> Clip:
        job = owned_job(job_id, user.id)
        updates = {}
        if body.publish is not None:
            updates["publish"] = body.publish
        if body.thumbnail_index is not None:
            updates["thumbnail_index"] = body.thumbnail_index
            clip = owned_clip(job, clip_id)
            if body.thumbnail_index < len(clip.thumbnails):
                updates["thumbnail"] = clip.thumbnails[body.thumbnail_index]
        if body.destinations is not None:
            updates["destinations"] = body.destinations
        if body.title is not None:
            updates["title"] = body.title[:100]
        if body.description is not None:
            updates["description"] = body.description[:2000]
        if body.tags is not None:
            updates["tags"] = [t.lower().strip() for t in body.tags][:15]

        clip = store.update_clip(job.id, clip_id, **updates)
        if clip is None:
            raise HTTPException(status_code=404, detail="clip not found")
        if body.publish and job.auto_publish and job.status == "done":
            enqueue_auto_publish(
                job.id, clip.id, str(store.root),
                job.auto_publish_platform, job.auto_publish_account,
            )
        return clip

    @app.post("/api/jobs/{job_id}/clips/{clip_id}/export", response_model=Clip)
    async def export(job_id: str, clip_id: str, user: User = Depends(get_current_user)) -> Clip:
        job = owned_job(job_id, user.id)
        clip = await export_clip(job.id, clip_id, store)
        if clip is None:
            raise HTTPException(status_code=404, detail="clip not found or job not done")
        return clip

    @app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
    def download(job_id: str, clip_id: str, user: User = Depends(get_current_user_media)) -> FileResponse:
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        if not clip.exported or not clip.export_name:
            raise HTTPException(status_code=404, detail="clip not exported")
        path = store.exports_dir(job.id) / clip.export_name
        if not path.exists():
            raise HTTPException(status_code=404, detail="export file missing")
        return FileResponse(path, filename=clip.export_name, media_type="video/mp4")

    @app.get("/api/jobs/{job_id}/clips/{clip_id}/preview")
    def preview(job_id: str, clip_id: str, user: User = Depends(get_current_user_media)) -> FileResponse:
        job = owned_job(job_id, user.id)
        clip = owned_clip(job, clip_id)
        if not clip.exported or not clip.export_name:
            raise HTTPException(status_code=404, detail="clip not exported")
        path = store.exports_dir(job.id) / clip.export_name
        if not path.exists():
            raise HTTPException(status_code=404, detail="export file missing")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/dashboard", response_model=DashboardStats)
    def dashboard(
        user: User = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> DashboardStats:
        stats = _build_dashboard(store, user.id)
        stats.accounts = len(
            list(db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user.id)))
        )
        return stats

    @app.get("/api/jobs/{job_id}/platforms", response_model=list[PlatformPost])
    def list_posts(job_id: str, user: User = Depends(get_current_user)) -> list[PlatformPost]:
        job = owned_job(job_id, user.id)
        return store.get_posts(job.id)

    @app.post(
        "/api/jobs/{job_id}/clips/{clip_id}/platforms", response_model=PlatformPost, status_code=201
    )
    def create_post(
        job_id: str, clip_id: str, body: PostCreate, user: User = Depends(get_current_user)
    ) -> PlatformPost:
        job = owned_job(job_id, user.id)
        owned_clip(job, clip_id)
        return store.create_post(job.id, clip_id, **body.model_dump())

    @app.patch("/api/jobs/{job_id}/platforms/{post_id}", response_model=PlatformPost)
    def update_post(
        job_id: str, post_id: str, body: PostCreate, user: User = Depends(get_current_user)
    ) -> PlatformPost:
        job = owned_job(job_id, user.id)
        post = store.update_post(job.id, post_id, **body.model_dump())
        if post is None:
            raise HTTPException(status_code=404, detail="post not found")
        return post

    @app.delete("/api/jobs/{job_id}/platforms/{post_id}", status_code=204)
    def delete_post(job_id: str, post_id: str, user: User = Depends(get_current_user)) -> None:
        job = owned_job(job_id, user.id)
        if not store.delete_post(job.id, post_id):
            raise HTTPException(status_code=404, detail="post not found")

    dist = BACKEND_DIR.parent / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/")
        def root() -> dict:
            return {
                "name": "ClipForge",
                "docs": "/docs",
                "hint": "Frontend no construido. Ejecuta 'cd web && npm run build'.",
            }

    return app


app = create_app()
