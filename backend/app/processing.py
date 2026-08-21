from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

from .llm_scorer import build_clip_selector, select_clips_safely
from .media import cut_clip, probe_duration
from .models import Clip
from .scorer import TOP_N
from .storage import JobStore
from .youtube import download_youtube


def _clip_id(index: int) -> str:
    return f"c{index}"


def _create_mock_video(duration: float, output_path: Path) -> None:
    """Create a mock video file for AI generation demo using ffmpeg."""
    try:
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=#1a1a2e:s=1080x1920:d={duration}:r=24",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            "-f", "mp4",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except Exception:
        with output_path.open("wb") as f:
            f.write(b"\x00" * 1024)


async def _ensure_source(job, store: JobStore):
    """Return the source path, downloading it first for YouTube jobs or creating mock for generate."""
    source = store.source_path(job.id)
    if source.exists():
        return source
    
    if job.source == "generate":
        job_dir = store.job_dir(job.id)
        meta_path = job_dir / "generate_meta.json"
        if not meta_path.exists():
            raise RuntimeError("No se encontro metadata de generación")
        meta = json.loads(meta_path.read_text())
        duration = float(meta.get("duration", 30))
        job.status = "processing"
        job.progress = 15
        store.save_job(job)
        await asyncio.to_thread(_create_mock_video, duration, source)
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
        
        if job.source == "generate":
            job_dir = store.job_dir(job.id)
            meta_path = job_dir / "generate_meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            prompt = meta.get("prompt", "Video generado con IA")
            clips = [
                Clip(
                    id=_clip_id(1),
                    index=1,
                    start=0.0,
                    end=min(duration, 30.0),
                    duration=min(duration, 30.0),
                    title=prompt[:60],
                    line=prompt[:120],
                    script=prompt,
                    score=1.0,
                )
            ]
            store.save_clips(job_id, clips)
            job.transcriber = "ai_generate"
            job.scorer = "ai_generate"
            job.clip_count = len(clips)
            job.status = "done"
            job.progress = 100
        else:
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
