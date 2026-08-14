from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.media import cut_clip, probe_duration
from app.processing import run_job
from app.storage import JobStore
from app.transcriber import MockTranscriber

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


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
    sample_video: Path, tmp_path: Path, auth_headers
) -> None:
    storage = tmp_path / "storage"
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)

    with sample_video.open("rb") as fh:
        resp = client.post(
            "/api/jobs", files={"file": ("sample.mp4", fh, "video/mp4")}, headers=auth_headers
        )
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    asyncio.run(run_job(job_id, JobStore(storage), transcriber))

    job = client.get(f"/api/jobs/{job_id}", headers=auth_headers).json()
    assert job["status"] == "done", job.get("error")
    assert job["clip_count"] > 0

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

    marked = client.patch(
        f"/api/jobs/{job_id}/clips/{target['id']}",
        json={"publish": True},
        headers=auth_headers,
    )
    assert marked.status_code == 200
    assert marked.json()["publish"] is True


def test_youtube_job_downloads_and_processes(
    sample_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_headers
) -> None:
    storage = tmp_path / "storage"
    store = JobStore(storage)
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)

    from app import processing

    async def fake_download(url, dest):
        (dest.parent / "source.mp4").write_bytes(sample_video.read_bytes())
        return str(dest.parent / "source.mp4"), "Mi video de YouTube"

    monkeypatch.setattr(processing, "download_youtube", fake_download)

    resp = client.post("/api/jobs/youtube", json={"url": "https://youtu.be/abc123"}, headers=auth_headers)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    asyncio.run(run_job(job_id, store, transcriber))

    job = client.get(f"/api/jobs/{job_id}", headers=auth_headers).json()
    assert job["status"] == "done", job.get("error")
    assert job["source"] == "youtube"
    assert job["filename"] == "Mi video de YouTube"
    assert job["clip_count"] > 0

    clips = client.get(f"/api/jobs/{job_id}/clips", headers=auth_headers).json()
    assert clips
    exported = client.post(
        f"/api/jobs/{job_id}/clips/{clips[0]['id']}/export", headers=auth_headers
    ).json()
    assert exported["exported"] is True
    assert exported["export_name"]
