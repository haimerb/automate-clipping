from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Clip, Job, PlatformPost


class JobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def upload_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "source"

    def source_path(self, job_id: str) -> Path:
        """Ruta real a la fuente: para uploads es `source` (sin extensión); para
        YouTube puede ser `source.mp4`/`source.webm` descargado por yt-dlp."""
        exact = self.upload_path(job_id)
        if exact.exists():
            return exact
        candidates = [
            p
            for p in exact.parent.glob(exact.name + ".*")
            if p.suffix not in {".part", ".ytdl", ".json"}
        ]
        if not candidates:
            return exact
        return max(candidates, key=lambda p: p.stat().st_size)

    def exports_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "exports"

    def archive_dir(self, job_id: str) -> Path:
        """Versiones previas del source, creadas al re-renderizar un job `generate`."""
        return self.job_dir(job_id) / "previous"

    def _source_candidates(self, job_id: str) -> list[Path]:
        exact = self.upload_path(job_id)
        return [
            p
            for p in exact.parent.glob(exact.name + ".*")
            if p.suffix not in {".part", ".ytdl", ".json"}
        ]

    def archive_source(self, job_id: str) -> Path | None:
        """Mueve (no copia) la fuente actual a `previous/source_<n>.<ext>`.

        Se usa antes de un re-render para no perder el video bueno si el
        generador falla: el pipeline vuelve a crear `source` desde cero.
        """
        source = self.source_path(job_id)
        if not source.exists():
            return None
        dest_dir = self.archive_dir(job_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            dest = dest_dir / f"source_{n}{source.suffix}"
            if not dest.exists():
                break
            n += 1
        shutil.move(str(source), str(dest))
        return dest

    def purge_media(self, job_id: str) -> int:
        """Borra source, exports, ai_tmp y previous. Devuelve los bytes liberados.

        Conserva `job.json`, `clips.json`, `posts.json` y `generate_meta.json`:
        el job sigue listado y se puede volver a renderizar desde su metadata.
        """
        freed = 0
        job_dir = self.job_dir(job_id)
        targets: list[Path] = list(self._source_candidates(job_id))
        if self.upload_path(job_id).exists():
            targets.append(self.upload_path(job_id))
        for folder in (self.exports_dir(job_id), job_dir / "ai_tmp", self.archive_dir(job_id)):
            if not folder.exists():
                continue
            for child in folder.rglob("*"):
                if child.is_file():
                    freed += child.stat().st_size
            shutil.rmtree(folder, ignore_errors=True)
        for path in targets:
            if path.exists():
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
        return freed

    def sweep_media(self, max_age_days: float = 7.0, keep: int = 1) -> dict[str, int]:
        """Limpieza global: recorta `previous/` y elimina `ai_tmp` huérfanos.

        - `previous/`: como máximo `keep` versiones por job y solo si son más
          antiguas que `max_age_days`.
        - `ai_tmp/`: carpetas sin `job.json` (job borrado a mitad) o de jobs ya
          terminados hace más de `max_age_days`.
        """
        import time

        now = time.time()
        removed_files = 0
        freed = 0
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            archive = self.archive_dir(child.name)
            if archive.is_dir():
                versions = sorted(
                    (p for p in archive.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for old in versions[keep:]:
                    if now - old.stat().st_mtime < max_age_days * 86400:
                        continue
                    freed += old.stat().st_size
                    old.unlink(missing_ok=True)
                    removed_files += 1
                if not any(archive.iterdir()):
                    archive.rmdir()

            tmp = child / "ai_tmp"
            if not tmp.is_dir():
                continue
            job_file = child / "job.json"
            stale = not job_file.exists()
            if not stale and max_age_days > 0:
                stale = (now - job_file.stat().st_mtime) > max_age_days * 86400
            if not stale:
                continue
            for f in tmp.rglob("*"):
                if f.is_file():
                    freed += f.stat().st_size
            removed_files += sum(1 for f in tmp.rglob("*") if f.is_file())
            shutil.rmtree(tmp, ignore_errors=True)
        return {"files": removed_files, "bytes": freed}

    def create_job(
        self,
        filename: str,
        source: str = "upload",
        source_url: str | None = None,
        owner_id: str | None = None,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        job = Job(
            id=job_id,
            filename=filename,
            source=source,
            source_url=source_url,
            owner_id=owner_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.save_job(job)
        return job

    def list_jobs(self, owner_id: str | None = None) -> list[Job]:
        jobs = []
        for child in sorted(self.root.iterdir(), key=lambda p: p.name):
            if child.is_dir():
                job = self.get_job(child.name)
                if job is not None and (owner_id is None or job.owner_id == owner_id):
                    jobs.append(job)
        return jobs

    def get_job(self, job_id: str) -> Job | None:
        path = self.job_dir(job_id) / "job.json"
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            return Job.model_validate_json(raw)
        except Exception:  # noqa: BLE001
            return None

    def save_job(self, job: Job) -> None:
        path = self.job_dir(job.id) / "job.json"
        path.write_text(job.model_dump_json(), encoding="utf-8")

    def save_clips(self, job_id: str, clips: list[Clip]) -> None:
        path = self.job_dir(job_id) / "clips.json"
        path.write_text(json.dumps([c.model_dump() for c in clips]), encoding="utf-8")

    def get_clips(self, job_id: str) -> list[Clip]:
        path = self.job_dir(job_id) / "clips.json"
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            return [Clip.model_validate(c) for c in json.loads(raw)]
        except (json.JSONDecodeError, ValueError):
            return []

    def update_clip(self, job_id: str, clip_id: str, **updates) -> Clip | None:
        clips = self.get_clips(job_id)
        for clip in clips:
            if clip.id == clip_id:
                for key, value in updates.items():
                    setattr(clip, key, value)
                self.save_clips(job_id, clips)
                return clip
        return None

    # ── platform posts ────────────────────────────────

    def _posts_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "posts.json"

    def get_posts(self, job_id: str) -> list[PlatformPost]:
        path = self._posts_path(job_id)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return []
            return [PlatformPost.model_validate(p) for p in json.loads(raw)]
        except (json.JSONDecodeError, ValueError):
            return []

    def save_posts(self, job_id: str, posts: list[PlatformPost]) -> None:
        path = self._posts_path(job_id)
        path.write_text(json.dumps([p.model_dump() for p in posts]), encoding="utf-8")
        job = self.get_job(job_id)
        if job is not None:
            job.post_count = len(posts)
            self.save_job(job)

    def create_post(self, job_id: str, clip_id: str, **values) -> PlatformPost:
        posts = self.get_posts(job_id)
        post = PlatformPost(
            id=uuid.uuid4().hex[:10],
            clip_id=clip_id,
            updated_at=datetime.now(timezone.utc).isoformat(),
            **values,
        )
        posts.append(post)
        self.save_posts(job_id, posts)
        return post

    def update_post(self, job_id: str, post_id: str, **updates) -> PlatformPost | None:
        posts = self.get_posts(job_id)
        for post in posts:
            if post.id == post_id:
                for key, value in updates.items():
                    setattr(post, key, value)
                post.updated_at = datetime.now(timezone.utc).isoformat()
                self.save_posts(job_id, posts)
                return post
        return None

    def delete_post(self, job_id: str, post_id: str) -> bool:
        posts = self.get_posts(job_id)
        remaining = [p for p in posts if p.id != post_id]
        if len(remaining) == len(posts):
            return False
        self.save_posts(job_id, remaining)
        return True
