from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai_generate import _size_for
from app.main import create_app
from app.media import probe_duration
from app.processing import run_job
from app.storage import JobStore
from app.transcriber import MockTranscriber

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

PROMPT = "El secreto para vender es entender la emoción antes que el producto."


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "storage", MockTranscriber()))


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
    stream = json.loads(result.stdout)["streams"][0]
    return stream["width"], stream["height"]


def _write_generate_meta(store: JobStore, job_id: str, **overrides) -> None:
    meta = {
        "prompt": PROMPT,
        "duration": 8,
        "style": "professional",
        "platform": "youtube_shorts",
        "voice": "es_mx_female",
        "auto_publish": False,
        "account_id": None,
        "auto_publish_account": None,
        **overrides,
    }
    (store.job_dir(job_id) / "generate_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )


# ── endpoint /api/generate ───────────────────────────────────


def test_generate_requires_auth(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/generate", json={"prompt": "hola", "duration": 15})
    assert resp.status_code == 401


def test_generate_endpoint_validations(tmp_path: Path, auth_headers) -> None:
    client = _client(tmp_path)
    # prompt vacío
    assert (
        client.post("/api/generate", json={"prompt": "   "}, headers=auth_headers).status_code
        == 422
    )
    # duración fuera del set permitido
    resp = client.post("/api/generate", json={"prompt": PROMPT, "duration": 45}, headers=auth_headers)
    assert resp.status_code == 422
    # duración sobre el máximo de youtube_shorts (60s)
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 120, "platform": "youtube_shorts"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # duración sobre el máximo de YouTube largo (180s)
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 180, "platform": "youtube"},
        headers=auth_headers,
    )
    assert resp.status_code == 202


def test_generate_endpoint_creates_job(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    client = _client(tmp_path)
    store = JobStore(storage)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)
    resp = client.post("/api/generate", json={"prompt": PROMPT, "duration": 15}, headers=auth_headers)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = store.get_job(job_id)
    assert job is not None
    assert job.source == "generate"
    assert job.owner_id

    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == PROMPT
    assert meta["duration"] == 15
    assert meta["platform"] == "youtube_shorts"


def test_generate_endpoint_resolves_account(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    client = _client(tmp_path)
    store = JobStore(storage)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)

    created = client.post(
        "/api/accounts",
        json={"platform": "youtube_shorts", "name": "Mi canal corto", "handle": "@micv"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 15, "auto_publish": True, "account_id": account_id},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert meta["auto_publish"] is True
    assert meta["auto_publish_account"] == "Mi canal corto"

    # cuenta inexistente → 422 sin crear job
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 15, "auto_publish": True, "account_id": "no-existe"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── pipeline (run_job, source="generate") ────────────────────


def _run_generate_job(
    tmp_path: Path,
    user_id: str,
    monkeypatch: pytest.MonkeyPatch,
    **meta_overrides,
) -> tuple[JobStore, str, list[tuple]]:
    storage = tmp_path / "storage"
    store = JobStore(storage)
    job = store.create_job(
        f"IA: {PROMPT[:40]}", source="generate", source_url=None, owner_id=user_id
    )
    _write_generate_meta(store, job.id, **meta_overrides)
    called: list[tuple] = []

    def _fake_enqueue(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr("app.ai_generate.build_voiceover", lambda *a, **k: None)
    monkeypatch.setattr("app.tasks.enqueue_auto_publish", _fake_enqueue)
    asyncio.run(run_job(job.id, store, MockTranscriber()))
    return store, job.id, called


def test_run_job_generate_vertical_short(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short real end-to-end: source vertical 9:16, clip exportado, metadata y auto-publish."""
    store, job_id, enqueued = _run_generate_job(
        tmp_path, user_id, monkeypatch, auto_publish=True, auto_publish_account="Canal Auto"
    )

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.transcriber == "ai_generate"
    assert job.scorer == "ai_generate"
    assert job.clip_count == 1
    assert job.auto_publish is True
    assert job.auto_publish_platform == "youtube_shorts"
    assert job.auto_publish_account == "Canal Auto"

    # la fuente real generada es vertical 9:16 (1080x1920)
    assert _video_size(store.source_path(job_id)) == (1080, 1920)

    clips = store.get_clips(job_id)
    assert len(clips) == 1
    clip = clips[0]
    assert clip.exported is True
    assert clip.export_name
    assert clip.title
    assert len(clip.script.strip()) >= 10
    exported = store.exports_dir(job_id) / clip.export_name
    assert exported.exists()
    assert _video_size(exported) == (1080, 1920)
    assert 0 < probe_duration(exported) <= 9.0

    # el guion del LLM (o su fallback) queda persistido para reuso
    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert "script_gen" in meta
    assert meta["script_gen"]["hook"]

    # auto-publish encolado con la cuenta destino
    assert any(
        args
        and args[0] == job_id
        and args[1] == clip.id
        and args[3] == "youtube_shorts"
        and args[4] == "Canal Auto"
        for args, _ in enqueued
    ), enqueued


def test_run_job_generate_youtube_horizontal(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube video largo: platform=youtube produce fuente horizontal 16:9."""
    store, job_id, _ = _run_generate_job(tmp_path, user_id, monkeypatch, platform="youtube")

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.clip_count == 1
    assert _video_size(store.source_path(job_id)) == (1920, 1080)

    clips = store.get_clips(job_id)
    assert clips and clips[0].exported is True
    exported = store.exports_dir(job_id) / clips[0].export_name
    assert exported.exists()
    assert _video_size(exported) == (1920, 1080)


def test_generate_source_respects_meta_prompt(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La fuente generada se usa igual que cualquier otra: se exporta y el clip la refleja."""
    store, job_id, _ = _run_generate_job(tmp_path, user_id, monkeypatch)
    clips = store.get_clips(job_id)
    assert clips
    assert clips[0].script.strip() == " ".join(PROMPT.split())


def test_ai_generate_size_for() -> None:
    assert _size_for("youtube") == (1920, 1080)
    assert _size_for("youtube_shorts") == (1080, 1920)
    assert _size_for("tiktok") == (1080, 1920)
    assert _size_for("instagram_reels") == (1080, 1920)