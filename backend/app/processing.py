from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

from .llm_scorer import build_clip_selector, select_clips_safely
from .media import cut_clip, extract_best_thumbnail, extract_multiple_thumbnails, probe_duration
from .models import Clip
from .scorer import TOP_N, _limits_for
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
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        duration = float(meta.get("duration", 30))
        job.status = "processing"
        job.progress = 15
        store.save_job(job)
        from . import ai_generate
        tmp = job_dir / "ai_tmp"
        try:
            await asyncio.to_thread(
                ai_generate.generate_ai_video, meta, meta_path, source, tmp
            )
        except ai_generate.ScriptGenerationError:
            # Sin guion no hay video: antes caía a un guion determinístico que
            # repetía el prompt y llenaba el clip de tarjetas de marca. Es mejor
            # un job `failed` con el motivo que un `done` inservible.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_generate falló (%s); usando mock de ffmpeg", exc)
            prev = job.warning
            note = "el generador con IA falló y se usó un video de prueba"
            job.warning = f"{prev}; {note}" if prev else note
            store.save_job(job)
            await asyncio.to_thread(_create_mock_video, duration, source)
        return source

    if job.source not in ("youtube", "url") or not job.source_url:
        raise RuntimeError("No se encontro el archivo de origen")
    job.status = "downloading"
    job.progress = 8
    store.save_job(job)
    path, title = await download_youtube(job.source_url, source)
    if title:
        job.filename = title
    return Path(path)


def _cleanup_ai_tmp(tmp: Path) -> None:
    """Borra los segmentos de render (el export ya está en `exports/`).

    Un job de 15 min deja cientos de MB de `_seg*.mp4` que nunca se vuelven a usar.
    """
    if not tmp.is_dir():
        return
    total = 0
    for f in tmp.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    shutil.rmtree(tmp, ignore_errors=True)
    logger.info("temporales de render eliminados: %.1f MB", total / 1e6)


def _extract_thumbnails(source: Path, clips: list[Clip], exports_dir: Path) -> None:
    """Extract the best thumbnail frame from each clip based on visual variance.

    Se escriben en el subdirectorio `thumbs/` del job (el endpoint `/thumb`
    sirve desde ahí); `exports_dir` solo marca la base del job para derivarlo.
    """
    thumbs_dir = exports_dir.parent / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    for clip in clips:
        try:
            thumb_name = f"{clip.id}_thumb.jpg"
            thumb_path = thumbs_dir / thumb_name
            extract_best_thumbnail(source, clip.start, clip.end, thumb_path)
            clip.thumbnail = thumb_name

            hook = " ".join((clip.line or clip.title).split())
            options = extract_multiple_thumbnails(
                source, clip.start, clip.end, thumbs_dir, clip.id,
                count=5, text=hook,
            )
            if options:
                clip.thumbnails = options
                clip.thumbnail = options[0]
                clip.thumbnail_index = 0
        except Exception:
            clip.thumbnail = None


def _infer_platform(duration: float, source_url: str | None = None) -> str:
    """Infer the target platform from video duration and source."""
    url = source_url or ""
    if "youtube.com/shorts" in url or "youtu.be/shorts" in url:
        return "youtube_shorts"
    if "tiktok.com" in url:
        return "tiktok"
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
        # La plataforma inferida manda en el export del paso de publicar. Un job
        # largo se exporta horizontal; solo se recorta a 60s si es un Short.
        job.platform = platform
        job.progress = 45
        store.save_job(job)

        if job.source == "generate":
            job_dir = store.job_dir(job.id)
            meta_path = job_dir / "generate_meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            prompt = meta.get("prompt", "Video generado con IA")
            platform = meta.get("platform", platform)
            # El paso de publicar lee `job.platform`; sin esto, un job `youtube`
            # (horizontal, 900s) se publicaba como Short (vertical, 60s).
            job.platform = platform
            store.save_job(job)
            script_info = meta.get("script_gen") or {}
            script_text = str(script_info.get("script") or prompt)[:3000]
            hook = str(script_info.get("hook") or prompt)[:120]
            title_hint = str(script_info.get("title") or prompt)[:60]
            notes = [str(w) for w in (script_info.get("warnings") or []) if str(w).strip()]
            if notes:
                job.warning = "; ".join(notes)
                store.save_job(job)
            _, max_dur = _limits_for(platform)
            clip_dur = min(duration, max_dur) if max_dur > 0 else duration
            clips = [
                Clip(
                    id=_clip_id(1),
                    index=1,
                    start=0.0,
                    end=clip_dur,
                    duration=clip_dur,
                    title=title_hint,
                    line=hook,
                    script=script_text,
                    score=1.0,
                )
            ]
            meta_result = generate_clip_metadata(metadata_gen, [
                {"script": script_text, "title": title_hint, "duration": clip_dur}
            ], platform, job.source_url)
            if meta_result:
                clips[0].title = meta_result[0].get("title", clips[0].title)
                clips[0].description = meta_result[0].get("description", "")
                clips[0].tags = meta_result[0].get("tags", [])

            store.save_clips(job_id, clips)

            job.progress = 85
            store.save_job(job)
            exports = store.exports_dir(job.id)
            exports.mkdir(parents=True, exist_ok=True)
            # la fuente generada ya nace con la orientación correcta (vertical/horizontal)
            gen_mode = os.environ.get("EDGETAPE_GENERATE_EXPORT_MODE", "original")
            for clip in clips:
                try:
                    safe = re.sub(r"[^\w.\-]", "_", clip.title).strip("_")[:40] or "clip"
                    out = exports / f"{clip.id}_{safe}.mp4"
                    await asyncio.to_thread(
                        cut_clip, source, clip.start, clip.end, out, gen_mode,
                        caption=clip.line or clip.script,
                    )
                    clip.exported = True
                    clip.export_name = out.name
                    clip.export_platform = platform
                except Exception:
                    logger.warning("export del clip %s falló", clip.id)
            _extract_thumbnails(source, clips, exports)
            store.save_clips(job_id, clips)

            job.transcriber = "ai_generate"
            job.scorer = "ai_generate"
            job.clip_count = len(clips)
            job.status = "done"
            job.progress = 100
            _cleanup_ai_tmp(store.job_dir(job.id) / "ai_tmp")
            auto_name = meta.get("auto_publish_account")
            if meta.get("auto_publish") and auto_name:
                job.auto_publish = True
                job.auto_publish_platform = platform or "youtube_shorts"
                job.auto_publish_account = auto_name
                store.save_job(job)
                from .tasks import enqueue_auto_publish
                for clip in clips:
                    enqueue_auto_publish(
                        job.id, clip.id, str(store.root),
                        job.auto_publish_platform, auto_name,
                    )
        else:
            trans_path = store.job_dir(job.id) / "transcription.json"
            colab_transcription = trans_path.exists()
            if colab_transcription:
                segments = json.loads(trans_path.read_text(encoding="utf-8"))
                logger.info("using %d segments from Colab transcription", len(segments))
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
            delay = float(os.environ.get("EDGETAPE_METADATA_DELAY", 5))
            if delay > 0:
                await asyncio.sleep(delay)
            found = generate_clip_metadata(metadata_gen, found, platform, job.source_url)
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

            job.transcriber = "colab-whisper" if colab_transcription else transcriber.name
            job.scorer = selector.name
            job.clip_count = len(clips)
            job.status = "done"
            job.progress = 100
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)
    store.save_job(job)


def _export_mode_for(job: Job, platform: str) -> str:
    """Modo de corte según la plataforma destino.

    `original` para formatos horizontales (YouTube video): aplicar `vertical_blur`
    a una fuente 1920x1080 la convierte en 1080x1920 con bandas, que es lo
    contrario de lo que se pidió. Los verticales (Shorts/TikTok/Reels) sí
    necesitan el blur para no recortar.
    """
    override = os.environ.get("EDGETAPE_EXPORT_MODE")
    if override:
        return override
    if platform in _HORIZONTAL_PLATFORMS:
        return "original"
    return "vertical_blur"


_HORIZONTAL_PLATFORMS = frozenset({"youtube", "otros"})


async def export_clip(
    job_id: str,
    clip_id: str,
    store: JobStore,
    max_duration: float | None = None,
    platform: str | None = None,
) -> Clip | None:
    job = store.get_job(job_id)
    if job is None or job.status != "done":
        return None
    clip = next((c for c in store.get_clips(job_id) if c.id == clip_id), None)
    if clip is None:
        return None
    target = platform or job.platform

    if clip.exported and clip.export_name:
        exports = store.exports_dir(job_id)
        out = exports / clip.export_name
        # Reutilizar solo si el export actual corresponde a la MISMA plataforma:
        # un clip ya cortado para Shorts (60s vertical) no vale para YouTube.
        same_target = clip.export_platform == target
        if same_target:
            if max_duration is None or max_duration <= 0:
                return clip
            try:
                existing = await asyncio.to_thread(probe_duration, out)
            except Exception:
                existing = float("inf")
            if existing <= max_duration:
                return clip

    exports = store.exports_dir(job_id)
    exports.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", clip.title).strip("_")[:40] or "clip"
    out = exports / f"{clip.id}_{safe}.mp4"
    mode = _export_mode_for(job, target)
    end = clip.end
    if max_duration is not None and max_duration > 0:
        end = min(end, clip.start + max_duration)
    if end <= clip.start:
        # El clip es más corto que el límite del formato: no se recorta nada,
        # así que no hace falta re-cortar (y `cut_clip` fallaría con d=0).
        end = clip.end
    await asyncio.to_thread(
        cut_clip, store.source_path(job_id), clip.start, end, out, mode,
        caption=clip.line or clip.script,
    )
    return store.update_clip(
        job_id, clip_id, exported=True, export_name=out.name, export_platform=target,
    )
