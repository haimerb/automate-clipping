from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

from .llm_scorer import build_clip_selector, select_clips_safely
from .media import cut_clip, extract_best_thumbnail, extract_thumbnail, probe_duration
from .models import Clip
from .scorer import TOP_N
from .storage import JobStore
from .viral import build_metadata_generator, generate_clip_metadata
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


def _extract_thumbnails(source: Path, clips: list[Clip], exports_dir: Path) -> None:
    """Extract the best thumbnail frame from each clip based on visual variance."""
    for clip in clips:
        try:
            thumb_name = f"{clip.id}_thumb.jpg"
            thumb_path = exports_dir / thumb_name
            extract_best_thumbnail(source, clip.start, clip.end, thumb_path)
            clip.thumbnail = thumb_name
        except Exception:
            clip.thumbnail = None


def _infer_platform(duration: float, source_url: str | None = None) -> str:
    """Infer the target platform from video duration and source."""
    if source_url and ("youtube.com/shorts" in source_url or "youtu.be/shorts" in source_url):
        return "youtube_shorts"
    if duration <= 65.0:
        return "youtube_shorts"
    return "youtube"


async def run_job(job_id: str, store: JobStore, transcriber, selector=None) -> None:
    job = store.get_job(job_id)
    if job is None:
        return
    selector = selector or build_clip_selector()
    metadata_gen = build_metadata_generator()
    job.status = "processing"
    store.save_job(job)
    try:
        source = await _ensure_source(job, store)

        job.progress = 15
        store.save_job(job)
        duration = await asyncio.to_thread(probe_duration, source)

        job.duration = duration
        platform = _infer_platform(duration, job.source_url)
        job.progress = 45
        store.save_job(job)
        
        if job.source == "generate":
            job_dir = store.job_dir(job.id)
            meta_path = job_dir / "generate_meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            prompt = meta.get("prompt", "Video generado con IA")
            platform = meta.get("platform", platform)
            clip_dur = min(duration, 60.0 if "short" in platform or "tiktok" in platform or "reels" in platform else 120.0)
            clips = [
                Clip(
                    id=_clip_id(1),
                    index=1,
                    start=0.0,
                    end=clip_dur,
                    duration=clip_dur,
                    title=prompt[:60],
                    line=prompt[:120],
                    script=prompt,
                    score=1.0,
                )
            ]
            meta_result = generate_clip_metadata(metadata_gen, [
                {"script": prompt, "title": prompt[:60], "duration": clip_dur}
            ], platform)
            if meta_result:
                clips[0].title = meta_result[0].get("title", clips[0].title)
                clips[0].description = meta_result[0].get("description", "")
                clips[0].tags = meta_result[0].get("tags", [])

            store.save_clips(job_id, clips)

            job.progress = 85
            store.save_job(job)
            exports = store.exports_dir(job.id)
            exports.mkdir(parents=True, exist_ok=True)
            for clip in clips:
                try:
                    safe = re.sub(r"[^\w.\-]", "_", clip.title).strip("_")[:40] or "clip"
                    out = exports / f"{clip.id}_{safe}.mp4"
                    mode = os.environ.get("EDGETAPE_EXPORT_MODE", "vertical_blur")
                    await asyncio.to_thread(
                        cut_clip, source, clip.start, clip.end, out, mode
                    )
                    store.update_clip(job.id, clip.id, exported=True, export_name=out.name)
                except Exception:
                    pass
            _extract_thumbnails(source, clips, exports)
            store.save_clips(job_id, clips)

            job.transcriber = "ai_generate"
            job.scorer = "ai_generate"
            job.clip_count = len(clips)
            job.status = "done"
            job.progress = 100
        else:
            segments = await asyncio.to_thread(transcriber.transcribe, str(source), duration)
            logger.info("transcribed %d segments, duration=%.1fs", len(segments), duration)

            job.progress = 60
            store.save_job(job)
            found = select_clips_safely(selector, segments, duration, TOP_N, platform)
            logger.info("found %d clips from selector %s", len(found), selector.name)
            for c in found:
                logger.info("  clip [%s-%s] script_len=%d title=%s",
                            c.get("start"), c.get("end"), len(c.get("script", "")),
                            c.get("title", "")[:40])

            job.progress = 70
            store.save_job(job)
            # Wait before metadata generation to avoid Groq 429 rate limit
            import time
            time.sleep(5)
            found = generate_clip_metadata(metadata_gen, found, platform)
            for c in found:
                logger.info("  metadata: title=%s desc_len=%d",
                            c.get("title", "")[:50], len(c.get("description", "")))

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
                    description=c.get("description", ""),
                    tags=c.get("tags", []),
                )
                for i, c in enumerate(found)
            ]

            job.progress = 80
            store.save_job(job)
            exports = store.exports_dir(job.id)
            exports.mkdir(parents=True, exist_ok=True)
            _extract_thumbnails(source, clips, exports)
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
