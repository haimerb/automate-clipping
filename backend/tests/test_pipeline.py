from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.media import cut_clip, probe_duration
from app.processing import run_job
from app.transcriber import MockTranscriber

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


def _wait_job(client: TestClient, job_id: str, headers: dict, timeout: float = 90.0) -> dict:
    """Espera a que el job termine (lo procesa el backend en segundo plano)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        if resp.status_code == 200:
            job = resp.json()
            if job.get("status") in ("done", "failed"):
                return job
        time.sleep(0.2)
    raise AssertionError(f"el job {job_id} no terminó a tiempo")


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=duration=90:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=90",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def test_probe_duration(sample_video: Path) -> None:
    duration = probe_duration(sample_video)
    assert 85 <= duration <= 95


def _video_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return stream["width"], stream["height"]


def test_cut_clip_vertical_blur_is_9_16(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "vertical.mp4"
    cut_clip(sample_video, 1.0, 6.0, out, mode="vertical_blur")
    assert out.exists()
    assert _video_size(out) == (1080, 1920)


def test_cut_clip_vertical_crop_is_9_16(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "vertical-crop.mp4"
    cut_clip(sample_video, 1.0, 6.0, out, mode="vertical_crop")
    assert out.exists()
    assert _video_size(out) == (1080, 1920)


def test_cut_clip_original_keeps_size(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "original.mp4"
    cut_clip(sample_video, 1.0, 6.0, out, mode="original")
    assert out.exists()
    assert _video_size(out) == (320, 240)


def test_full_pipeline_end_to_end(
    sample_video: Path, tmp_path: Path, auth_headers, auth_token
) -> None:
    from app import main as _main_mod
    from app.storage import JobStore

    storage = tmp_path / "storage"
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)
    store = JobStore(storage)

    _orig_enqueue = _main_mod.enqueue_job
    _main_mod.enqueue_job = lambda *a, **kw: None
    try:
        with sample_video.open("rb") as fh:
            resp = client.post(
                "/api/jobs", files={"file": ("sample.mp4", fh, "video/mp4")}, headers=auth_headers
            )
        assert resp.status_code == 202
        job_id = resp.json()["id"]

        asyncio.run(run_job(job_id, store, transcriber))
    finally:
        _main_mod.enqueue_job = _orig_enqueue

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.clip_count > 0

    clips = client.get(f"/api/jobs/{job_id}/clips", headers=auth_headers).json()
    assert clips

    target = clips[0]
    exported = client.post(
        f"/api/jobs/{job_id}/clips/{target['id']}/export", headers=auth_headers
    ).json()
    assert exported["exported"] is True
    assert exported["export_name"]

    dl = client.get(f"/api/jobs/{job_id}/clips/{target['id']}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "video/mp4"

    export_path = tmp_path / "downloaded.mp4"
    export_path.write_bytes(dl.content)
    clipped_duration = probe_duration(export_path)
    assert 0 < clipped_duration <= target["duration"] + 1.0

    preview = client.get(f"/api/jobs/{job_id}/clips/{target['id']}/preview", headers=auth_headers)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "video/mp4"

    preview = client.get(
        f"/api/jobs/{job_id}/clips/{target['id']}/preview?token={auth_token}",
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "video/mp4"

    missing = client.get(
        f"/api/jobs/{job_id}/clips/{target['id']}/preview?token=token-falso",
    )
    assert missing.status_code == 401

    marked = client.patch(
        f"/api/jobs/{job_id}/clips/{target['id']}",
        json={"publish": True},
        headers=auth_headers,
    )
    assert marked.status_code == 200
    assert marked.json()["publish"] is True


def test_run_job_uses_preexisting_transcription(
    sample_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    """El flujo Colab: si existe transcription.json, run_job lo usa sin re-transcribir."""
    from app import main as _main_mod
    from app.storage import JobStore

    storage = tmp_path / "storage"
    store = JobStore(storage)
    app = create_app(storage, MockTranscriber())
    client = TestClient(app)

    async def fake_download(url, dest):
        (dest.parent / "source.mp4").write_bytes(sample_video.read_bytes())
        return str(dest.parent / "source.mp4"), "Video para Colab"

    _orig_enqueue = _main_mod.enqueue_job
    _main_mod.enqueue_job = lambda *a, **kw: None
    _orig_dl = run_job.__globals__["download_youtube"]
    run_job.__globals__["download_youtube"] = fake_download

    class ExplodingTranscriber:
        """Si run_job llama a transcribe, falla el test."""

        name = "exploding"

        def transcribe(self, path: str, duration: float) -> list[dict]:
            raise AssertionError("run_job no debe transcribir cuando existe transcription.json")

    try:
        job = store.create_job(
            "Video para Colab", source="youtube", source_url="https://youtu.be/abc123"
        )
        job_dir = store.job_dir(job.id)
        segments = [
            {"start": 0.5, "end": 4.5, "text": "La conclusión clave es que esta fue la decisión más importante."},
            {"start": 5.0, "end": 9.0, "text": "Esto es lo que nadie te cuenta: la primera versión simplemente fracasó."},
            {"start": 9.5, "end": 13.5, "text": "El secreto de una buena edición es saber exactamente qué dejar fuera."},
            {"start": 14.0, "end": 18.0, "text": "Nunca subestimes lo importante que es un buen inicio, porque lo decide todo."},
            {"start": 18.5, "end": 22.5, "text": "La mejor lección de ese proyecto fue aprender a decir que no a tiempo."},
            {"start": 23.0, "end": 27.0, "text": "El mayor error que cometimos fue esconder nuestra mejor historia."},
            {"start": 27.5, "end": 31.5, "text": "La verdad incómoda es que la mayoría abandona antes del tercer video."},
            {"start": 32.0, "end": 36.0, "text": "Por fin le dijimos la verdad al cliente sobre su idea, y funcionó."},
            {"start": 36.5, "end": 40.5, "text": "Nadie te dice esto pero la clave no es la calidad del equipo."},
        ]
        (job_dir / "transcription.json").write_text(json.dumps(segments), encoding="utf-8")

        asyncio.run(run_job(job.id, store, ExplodingTranscriber()))
    finally:
        run_job.__globals__["download_youtube"] = _orig_dl
        _main_mod.enqueue_job = _orig_enqueue

    job = store.get_job(job.id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.transcriber == "colab-whisper"
    assert job.clip_count > 0

    task = client.get(f"/api/jobs/{job.id}/task")
    assert task.status_code == 200
    assert task.json()["source_url"] == "https://youtu.be/abc123"
    assert task.json()["status"] == "done"


def test_youtube_job_downloads_and_processes(
    sample_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    from app import main as _main_mod
    from app.storage import JobStore

    storage = tmp_path / "storage"
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)
    store = JobStore(storage)

    async def fake_download(url, dest):
        (dest.parent / "source.mp4").write_bytes(sample_video.read_bytes())
        return str(dest.parent / "source.mp4"), "Mi video de YouTube"

    _orig_enqueue = _main_mod.enqueue_job
    _main_mod.enqueue_job = lambda *a, **kw: None
    _orig_dl = run_job.__globals__["download_youtube"]
    run_job.__globals__["download_youtube"] = fake_download
    try:
        resp = client.post("/api/jobs/youtube", json={"url": "https://youtu.be/abc123"}, headers=auth_headers)
        assert resp.status_code == 202
        job_id = resp.json()["id"]

        asyncio.run(run_job(job_id, store, transcriber))
    finally:
        run_job.__globals__["download_youtube"] = _orig_dl
        _main_mod.enqueue_job = _orig_enqueue

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.source == "youtube"
    assert job.filename == "Mi video de YouTube"
    assert job.clip_count > 0

    clips = client.get(f"/api/jobs/{job_id}/clips", headers=auth_headers).json()
    assert clips
    exported = client.post(
        f"/api/jobs/{job_id}/clips/{clips[0]['id']}/export", headers=auth_headers
    ).json()
    assert exported["exported"] is True
    assert exported["export_name"]
