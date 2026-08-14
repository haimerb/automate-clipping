from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from .llm_scorer import build_clip_selector, select_clips_safely
from .media import cut_clip, probe_duration
from .models import Clip
from .scorer import TOP_N
from .storage import JobStore
from .youtube import download_youtube


def _clip_id(index: int) -> str:
    return f"c{index}"


async def _ensure_source(job, store: JobStore):
    """Return the source path, downloading it first for YouTube jobs."""
    source = store.source_path(job.id)
    if source.exists():
        return source
    if job.source != "youtube" or not job.source_url:
        raise RuntimeError("No se encontro el archivo de origen")
    job.status = "downloading"
    job.progress = 8
    store.save_job(job)
    path, title = await download_youtube(job.source_url, source)
    if title:
        job.filename = title
    return Path(path)


async def run_job(job_id: str, store: JobStore, transcriber, selector=None) -> None:
    job = store.get_job(job_id)
    if job is None:
        return
    selector = selector or build_clip_selector()
    job.status = "processing"
    store.save_job(job)
    try:
        source = await _ensure_source(job, store)

        job.progress = 15
        store.save_job(job)
        duration = await asyncio.to_thread(probe_duration, source)

        job.duration = duration
        job.progress = 45
        store.save_job(job)
        segments = await asyncio.to_thread(transcriber.transcribe, str(source), duration)

        job.progress = 75
        store.save_job(job)
        found = select_clips_safely(selector, segments, duration, TOP_N)

        clips = [
            Clip(
                id=_clip_id(i + 1),
                index=i + 1,
                start=c["start"],
                end=c["end"],
                duration=c["duration"],
                title=c["title"],
                line=c["line"],
                script=c["script"],
                score=c["score"],
            )
            for i, c in enumerate(found)
        ]
        store.save_clips(job_id, clips)

        job.transcriber = transcriber.name
        job.scorer = selector.name
        job.clip_count = len(clips)
        job.status = "done"
        job.progress = 100
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)
    store.save_job(job)


async def export_clip(job_id: str, clip_id: str, store: JobStore) -> Clip | None:
    job = store.get_job(job_id)
    if job is None or job.status != "done":
        return None
    clip = next((c for c in store.get_clips(job_id) if c.id == clip_id), None)
    if clip is None:
        return None
    if clip.exported and clip.export_name:
        return clip

    exports = store.exports_dir(job_id)
    exports.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", clip.title).strip("_")[:40] or "clip"
    out = exports / f"{clip.id}_{safe}.mp4"
    mode = os.environ.get("EDGETAPE_EXPORT_MODE", "vertical_blur")
    await asyncio.to_thread(
        cut_clip, store.source_path(job_id), clip.start, clip.end, out, mode
    )
    return store.update_clip(
        job_id, clip_id, exported=True, export_name=out.name
    )
