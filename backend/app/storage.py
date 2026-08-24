from __future__ import annotations

import json
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
