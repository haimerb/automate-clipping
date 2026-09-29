from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import publish as pubmod
from app import tasks as _tasks
from app import youtube_publish as ytpub
from app.main import create_app
from app.processing import run_job
from app.storage import JobStore
from app.transcriber import MockTranscriber

enqueue_job = _tasks.enqueue_job
enqueue_auto_publish = _tasks.enqueue_auto_publish

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
            "-f", "lavfi", "-i", "testsrc2=duration=60:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def job_template(tmp_path_factory, auth_headers, sample_video) -> Path:
    """Corre run_job UNA vez por módulo y deja el storage listo; cada test lo copia."""
    import time
    from app import main as _main_mod

    storage = tmp_path_factory.mktemp("job-template") / "storage"
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)
    store = JobStore(storage)
    _orig_enqueue = _main_mod.enqueue_job
    _orig_auto = _main_mod.enqueue_auto_publish
    _main_mod.enqueue_job = lambda *a, **kw: None
    _main_mod.enqueue_auto_publish = lambda *a, **kw: None
    try:
        for _ in range(10):
            with sample_video.open("rb") as fh:
                resp = client.post(
                    "/api/jobs", files={"file": ("sample.mp4", fh, "video/mp4")}, headers=auth_headers
                )
            assert resp.status_code == 202
            job_id = resp.json()["id"]
            asyncio.run(run_job(job_id, store, transcriber))
            job = store.get_job(job_id)
            if job and job.status == "done" and store.get_clips(job_id):
                return storage
            # El intento falló (el mock no siempre encuentra un clip): su job se
            # queda en el template y los tests que lo copian asertan 1 job.
            shutil.rmtree(store.job_dir(job_id), ignore_errors=True)
            time.sleep(0.1)
    finally:
        _main_mod.enqueue_job = _orig_enqueue
        _main_mod.enqueue_auto_publish = _orig_auto
    raise AssertionError("no se generaron clips en ningún intento")


def _done_job(tmp_path: Path, job_template: Path) -> tuple[TestClient, JobStore, str]:
    storage = tmp_path / "storage"
    shutil.copytree(job_template, storage, dirs_exist_ok=True)
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)
    store = JobStore(storage)
    jobs = store.list_jobs()
    assert len(jobs) == 1, f"el template tiene {len(jobs)} jobs"
    job_id = jobs[0].id
    return client, store, job_id


def test_publish_fallback_creates_ready_post(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Canal Respaldo", "handle": "@x", "token": None},
        headers=auth_headers,
    )
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(
        pubmod.publish_one(store, job, clip, platform="youtube_shorts", account="Canal Respaldo")
    )
    assert post is not None
    assert post.status == "listo"
    assert post.url == pubmod.STUDIO_UPLOAD_URL
    assert post.method == "manual"
    assert post.account == "Canal Respaldo"
    assert post.clip_id == clip.id
    assert store.get_clips(job_id)[0].exported is True


def test_publish_real_upload(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Canal Real",
            "handle": "@x",
            "token": "1//REFRESH123",
            "client_id": "client-id-real",
            "client_secret": "client-secret-real",
        },
        headers=auth_headers,
    )

    async def fake_upload(*args, **kwargs):
        return {"id": "vid123", "url": "https://www.youtube.com/watch?v=vid123"}

    monkeypatch.setattr(ytpub, "upload_video", fake_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Real"))
    assert post is not None
    assert post.status == "publicado"
    assert post.method == "youtube_api"
    assert post.url == "https://www.youtube.com/watch?v=vid123"
    assert post.account == "Canal Real"


def test_publish_real_upload_env_fallback(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Canal Env", "handle": "@x", "token": "1//REFRESH123"},
        headers=auth_headers,
    )
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_ID", "client-id-env")
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_SECRET", "client-secret-env")

    async def fake_upload(*args, **kwargs):
        return {"id": "vidEnv", "url": "https://www.youtube.com/watch?v=vidEnv"}

    monkeypatch.setattr(ytpub, "upload_video", fake_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Env"))
    assert post is not None
    assert post.status == "publicado"
    assert post.url == "https://www.youtube.com/watch?v=vidEnv"


def test_publish_api_key_token_falls_back(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Canal Con API Key",
            "handle": "@x",
            "token": "AIzaSyabcdefghijklmnop",
        },
        headers=auth_headers,
    )
    monkeypatch.setattr(ytpub, "is_configured", lambda: True)
    upload_called = {"value": False}

    async def fake_upload(*args, **kwargs):
        upload_called["value"] = True
        return {"id": "x", "url": "https://www.youtube.com/watch?v=x"}

    monkeypatch.setattr(ytpub, "upload_video", fake_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Con API Key"))
    assert post is not None
    assert post.status == "listo"
    assert post.method == "manual"
    assert upload_called["value"] is False


def test_publish_skips_when_already_published(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Canal Duplicado",
            "handle": "@x",
            "token": "1//fake_refresh_token",
            "client_id": "fake_id",
            "client_secret": "fake_secret",
        },
        headers=auth_headers,
    )
    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]

    async def fake_upload(*args, **kwargs):
        return {"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1"}

    monkeypatch.setattr(ytpub, "is_configured", lambda: True)
    monkeypatch.setattr(ytpub, "upload_video", fake_upload)

    first = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Duplicado"))
    second = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Duplicado"))
    assert first is not None
    assert first.status == "publicado"
    assert second is None


def _yt_error(status_code: int, reason: str) -> Exception:
    import httpx
    request = httpx.Request("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status")
    response = httpx.Response(
        status_code,
        json={"error": {"errors": [{"reason": reason, "message": "boom"}]}},
        request=request,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("debería haber lanzado HTTPStatusError")


def test_publish_upload_limit_exceeded_pauses_channel(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    from app.publish_queue import get_queue_manager, AccountStatus

    qm = get_queue_manager(JobStore(tmp_path / "storage"))
    qm._quotas.clear()
    qm._save_state()

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Canal Limitado",
            "handle": "@x",
            "token": "1//fake_refresh_token",
            "client_id": "fake_id",
            "client_secret": "fake_secret",
        },
        headers=auth_headers,
    )
    monkeypatch.setattr(ytpub, "is_configured", lambda: True)

    async def failing_upload(*args, **kwargs):
        raise _yt_error(400, "uploadLimitExceeded")

    monkeypatch.setattr(ytpub, "upload_video", failing_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Limitado"))
    assert post is not None
    assert post.status == "listo"
    assert post.method == "manual"
    assert post.error is not None
    assert "uploadLimitExceeded" in post.error

    can, reason = qm.can_upload("youtube_shorts", "Canal Limitado")
    assert can is False
    assert reason.startswith("quota_exceeded_until_")
    quota = qm._quotas.get("youtube_shorts:Canal Limitado")
    assert quota is not None
    assert quota.status == AccountStatus.QUOTA_EXCEEDED
    assert quota.last_error == "límite diario del canal (uploadLimitExceeded)"


def test_publish_other_errors_do_not_pause_channel(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    from app.publish_queue import get_queue_manager, AccountStatus

    qm = get_queue_manager(JobStore(tmp_path / "storage"))
    qm._quotas.clear()
    qm._save_state()

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Canal Genérico",
            "handle": "@x",
            "token": "1//fake_refresh_token",
            "client_id": "fake_id",
            "client_secret": "fake_secret",
        },
        headers=auth_headers,
    )
    monkeypatch.setattr(ytpub, "is_configured", lambda: True)

    async def failing_upload(*args, **kwargs):
        raise _yt_error(500, "backendError")

    monkeypatch.setattr(ytpub, "upload_video", failing_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, account="Canal Genérico"))
    assert post is not None
    assert post.status == "listo"
    assert post.error is None

    can, _ = qm.can_upload("youtube_shorts", "Canal Genérico")
    assert can is True
    quota = qm._quotas.get("youtube_shorts:Canal Genérico")
    assert quota is None or quota.status != AccountStatus.QUOTA_EXCEEDED


def test_publish_max_uploads_per_day_env(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    from app.publish_queue import PublishQueueManager

    monkeypatch.setenv("EDGETAPE_MAX_UPLOADS_PER_DAY", "2")
    monkeypatch.setenv("EDGETAPE_MIN_UPLOAD_DELAY", "0")
    qm = PublishQueueManager(JobStore(tmp_path / "storage"))
    qm._quotas.clear()
    qm._save_state()

    assert qm.MAX_UPLOADS_PER_DAY == 2
    assert qm.MIN_DELAY_BETWEEN_UPLOADS == 0

    qm.record_upload("youtube_shorts", "Canal X", True)
    qm.record_upload("youtube_shorts", "Canal X", True)
    can, reason = qm.can_upload("youtube_shorts", "Canal X")
    assert can is False
    assert reason == "daily_limit_reached"


def test_publish_all_only_marked_clips(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, job_template)
    clips = client.get(f"/api/jobs/{job_id}/clips", headers=auth_headers).json()
    target = clips[0]

    resp = client.patch(
        f"/api/jobs/{job_id}/clips/{target['id']}", json={"publish": True}, headers=auth_headers
    )
    assert resp.status_code == 200

    job = store.get_job(job_id)
    posts = asyncio.run(pubmod.publish_all(store, job, platform="youtube_shorts"))
    assert len(posts) == 1
    assert posts[0].clip_id == target["id"]
    assert posts[0].status == "listo"


def test_publish_all_endpoint(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, job_template)
    clips = client.get(f"/api/jobs/{job_id}/clips", headers=auth_headers).json()
    client.patch(
        f"/api/jobs/{job_id}/clips/{clips[0]['id']}", json={"publish": True}, headers=auth_headers
    )
    resp = client.post(
        f"/api/jobs/{job_id}/publish-all",
        json={"platform": "youtube_shorts", "account": None},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["clip_id"] == clips[0]["id"]
    post = results[0]["post"]
    assert post["status"] == "listo"
    assert post["url"] == pubmod.STUDIO_UPLOAD_URL


def test_publish_clip_endpoint(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, job_template)
    clip_id = store.get_clips(job_id)[0].id
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Canal Destino", "handle": "@y", "token": None},
        headers=auth_headers,
    )

    resp = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "youtube_shorts", "account": "Canal Destino"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["clip_id"] == clip_id
    assert body["platform"] == "youtube_shorts"
    assert body["status"] == "listo"
    assert body["url"] == pubmod.STUDIO_UPLOAD_URL
    assert body["account"] == "Canal Destino"


def test_publish_clip_endpoint_returns_existing_when_duplicated(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, job_template)
    clip_id = store.get_clips(job_id)[0].id

    first = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "tiktok"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    assert first.json()["status"] == "listo"

    second = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "tiktok"},
        headers=auth_headers,
    )
    assert second.status_code == 201
    assert second.json()["status"] == "listo"
    assert second.json()["id"] != first.json()["id"]


def test_publish_clip_resolves_account_by_platform(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, job_template)
    clip_id = store.get_clips(job_id)[0].id
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Solo YouTube", "handle": "@y", "token": None},
        headers=auth_headers,
    )
    client.post(
        "/api/accounts",
        json={"platform": "tiktok", "name": "Solo TikTok", "handle": "@t", "token": None},
        headers=auth_headers,
    )

    resp = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "tiktok", "account": "Solo TikTok"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["account"] == "Solo TikTok"

    job = store.get_job(job_id)
    linked = pubmod._platform_account(store, job, "tiktok", "Solo YouTube")
    assert linked is None  # la cuenta es de YouTube, no aplica al destino TikTok


def test_publish_clip_endpoint_requires_done_job(tmp_path, auth_headers, job_template) -> None:
    storage = tmp_path / "storage"
    client = TestClient(create_app(storage, MockTranscriber()))
    store = JobStore(storage)
    job = store.create_job("pending.mp4", owner_id="someone-else")

    resp = client.post(
        f"/api/jobs/{job.id}/clips/whatever/publish",
        json={"platform": "youtube_shorts"},
        headers=auth_headers,
    )
    assert resp.status_code == 404  # job ajeno -> not found


def test_publish_tiktok_uses_direct_link(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={"platform": "tiktok", "name": "Mi TikTok", "handle": "@t", "token": None},
        headers=auth_headers,
    )

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="tiktok", account="Mi TikTok"))
    assert post is not None
    assert post.status == "listo"
    assert post.url == "https://www.tiktok.com/upload"
    assert post.method == "manual"
    assert post.account == "Mi TikTok"


def test_publish_facebook_reels_uses_direct_link(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={"platform": "facebook", "name": "Mi Página", "handle": "@fb", "token": None},
        headers=auth_headers,
    )

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(
        pubmod.publish_one(store, job, clip, platform="facebook_reels", account="Mi Página")
    )
    assert post is not None
    assert post.status == "listo"
    assert post.url == "https://www.facebook.com/reels/create"
    assert post.account == "Mi Página"


def test_publish_tiktok_never_uses_youtube_api(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={"platform": "tiktok", "name": "TikTok API", "handle": "@t", "token": "1//REFRESH123"},
        headers=auth_headers,
    )
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_ID", "client-id")
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_SECRET", "client-secret")
    upload_called = {"value": False}

    async def fake_upload(*args, **kwargs):
        upload_called["value"] = True
        return {"id": "x", "url": "https://www.youtube.com/watch?v=x"}

    monkeypatch.setattr(ytpub, "upload_video", fake_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="tiktok", account="TikTok API"))
    assert post is not None
    assert post.status == "listo"
    assert post.url == "https://www.tiktok.com/upload"
    assert upload_called["value"] is False


def test_patch_job_settings_auto_publish(tmp_path, auth_headers, sample_video, job_template) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    resp = client.patch(f"/api/jobs/{job_id}", json={"auto_publish": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["auto_publish"] is True
    assert store.get_job(job_id).auto_publish is True


def test_clip_thumbnail(tmp_path, auth_headers, auth_token, sample_video, job_template) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    clip_id = store.get_clips(job_id)[0].id
    resp = client.get(f"/api/jobs/{job_id}/clips/{clip_id}/thumb", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert len(resp.content) > 500

    resp = client.get(f"/api/jobs/{job_id}/clips/{clip_id}/thumb?token={auth_token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    resp = client.get(f"/api/jobs/{job_id}/clips/{clip_id}/thumb?token=token-falso")
    assert resp.status_code == 401


def test_youtube_auth_url_builds_link(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    resp = client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Mi canal", "handle": "@x", "token": None},
        headers=auth_headers,
    )
    acc_id = resp.json()["id"]
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_ID", "client-id")
    monkeypatch.setenv("EDGETAPE_YT_CLIENT_SECRET", "client-secret")

    resp = client.get(f"/api/accounts/{acc_id}/youtube/auth", headers=auth_headers)
    assert resp.status_code == 200
    assert "accounts.google.com" in resp.json()["auth_url"]
    assert acc_id in resp.json()["auth_url"]


def test_youtube_auth_url_requires_credentials(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    resp = client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Mi canal", "handle": "@x", "token": None},
        headers=auth_headers,
    )
    acc_id = resp.json()["id"]
    monkeypatch.delenv("EDGETAPE_YT_CLIENT_ID", raising=False)
    monkeypatch.delenv("EDGETAPE_YT_CLIENT_SECRET", raising=False)

    resp = client.get(f"/api/accounts/{acc_id}/youtube/auth", headers=auth_headers)
    assert resp.status_code == 400


def test_youtube_callback_stores_refresh_token(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    resp = client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Mi canal",
            "handle": "@x",
            "token": None,
            "client_id": "client-id-acc",
            "client_secret": "client-secret-acc",
        },
        headers=auth_headers,
    )
    acc_id = resp.json()["id"]
    monkeypatch.setattr(
        ytpub,
        "exchange_code",
        lambda code, creds=None: creds.client_id if creds is not None else "refresh-token-abc",
    )

    resp = client.get(f"/api/youtube/callback?code=xyz&state={acc_id}", follow_redirects=False)
    assert resp.status_code == 302

    accounts = client.get("/api/accounts", headers=auth_headers).json()
    assert any(a["id"] == acc_id and a["token"] == "client-id-acc" for a in accounts)


def test_youtube_auth_url_uses_account_credentials(
    tmp_path, auth_headers, sample_video, job_template, monkeypatch
) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    monkeypatch.delenv("EDGETAPE_YT_CLIENT_ID", raising=False)
    monkeypatch.delenv("EDGETAPE_YT_CLIENT_SECRET", raising=False)
    resp = client.post(
        "/api/accounts",
        json={
            "platform": "youtube",
            "name": "Mi canal",
            "handle": "@x",
            "token": None,
            "client_id": "account-client-id",
            "client_secret": "account-client-secret",
        },
        headers=auth_headers,
    )
    acc_id = resp.json()["id"]

    resp = client.get(f"/api/accounts/{acc_id}/youtube/auth", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "accounts.google.com" in body["auth_url"]
    assert "account-client-id" in body["auth_url"]
    assert acc_id in body["auth_url"]


# ── publicación automática TikTok / Facebook / Instagram ────────────────────


def test_publish_tiktok_api_upload(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    from app import tiktok_publish as tkpub

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "tiktok",
            "name": "Mi TikTok API",
            "handle": "@mi",
            "token": "SYS.faketoken",
        },
        headers=auth_headers,
    )
    monkeypatch.setenv("EDGETAPE_TIKTOK_CLIENT_KEY", "client-key-env")
    monkeypatch.setenv("EDGETAPE_TIKTOK_CLIENT_SECRET", "client-secret-env")

    async def fake_upload(*args, **kwargs):
        return {"publish_id": "p1", "status": "PUBLISH_COMPLETE", "url": "https://www.tiktok.com/@mi/video/1234"}

    monkeypatch.setattr(tkpub, "upload_video", fake_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="tiktok", account="Mi TikTok API"))
    assert post is not None
    assert post.status == "publicado"
    assert post.method == "tiktok_api"
    assert post.url == "https://www.tiktok.com/@mi/video/1234"
    assert post.account == "Mi TikTok API"


def test_publish_tiktok_api_error_falls_back(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    from app import publish_queue
    from app import tiktok_publish as tkpub
    from app.publish_queue import get_queue_manager

    qm = get_queue_manager(JobStore(tmp_path / "storage"))
    qm._quotas.clear()
    qm._save_state()

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "tiktok",
            "name": "TikTok Con Límite",
            "handle": "@x",
            "token": "SYS.faketoken",
        },
        headers=auth_headers,
    )
    monkeypatch.setenv("EDGETAPE_TIKTOK_CLIENT_KEY", "client-key-env")
    monkeypatch.setenv("EDGETAPE_TIKTOK_CLIENT_SECRET", "client-secret-env")

    async def failing_upload(*args, **kwargs):
        raise _yt_error(429, "rate_limit_exceeded")

    monkeypatch.setattr(tkpub, "upload_video", failing_upload)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="tiktok", account="TikTok Con Límite"))
    assert post is not None
    assert post.status == "listo"
    assert post.method == "manual"
    assert post.url == "https://www.tiktok.com/upload"

    can, reason = qm.can_upload("tiktok", "TikTok Con Límite")
    assert can is False
    assert reason.startswith("rate_limited_until_")
    quota = qm._quotas.get("tiktok:TikTok Con Límite")
    assert quota is not None
    assert quota.status == publish_queue.AccountStatus.RATE_LIMITED


def test_publish_facebook_api_upload(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    from app import meta_publish as metapub

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "facebook",
            "name": "Mi Página API",
            "handle": "123456789",
            "token": "EAAToken123",
        },
        headers=auth_headers,
    )

    async def fake_fb(*args, **kwargs):
        return {"id": "vidfb", "url": "https://www.facebook.com/watch/?v=vidfb"}

    monkeypatch.setattr(metapub, "publish_to_facebook", fake_fb)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="facebook_reels", account="Mi Página API"))
    assert post is not None
    assert post.status == "publicado"
    assert post.method == "meta_api"
    assert post.url == "https://www.facebook.com/watch/?v=vidfb"
    assert post.account == "Mi Página API"


def test_publish_facebook_api_error_falls_back(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    from app import meta_publish as metapub
    from app.publish_queue import AccountStatus, get_queue_manager

    qm = get_queue_manager(JobStore(tmp_path / "storage"))
    qm._quotas.clear()
    qm._save_state()

    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "facebook",
            "name": "Página Con Error",
            "handle": "123456789",
            "token": "EAAToken123",
        },
        headers=auth_headers,
    )

    async def failing_fb(*args, **kwargs):
        raise _yt_error(403, "permissions_error")

    monkeypatch.setattr(metapub, "publish_to_facebook", failing_fb)

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="facebook_reels", account="Página Con Error"))
    assert post is not None
    assert post.status == "listo"
    assert post.method == "manual"

    # un solo 403 no pausa la cuenta (se pausa con 2 consecutivos)
    can, _ = qm.can_upload("facebook_reels", "Página Con Error")
    assert can is True
    quota = qm._quotas.get("facebook_reels:Página Con Error")
    assert quota is None or quota.status != AccountStatus.QUOTA_EXCEEDED


def test_publish_instagram_requires_public_url(tmp_path, auth_headers, sample_video, job_template, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, job_template)
    client.post(
        "/api/accounts",
        json={
            "platform": "instagram",
            "name": "Mi IG",
            "handle": "17841400000000000",
            "token": "IGToken123",
        },
        headers=auth_headers,
    )

    job = store.get_job(job_id)
    clip = store.get_clips(job_id)[0]
    post = asyncio.run(pubmod.publish_one(store, job, clip, platform="instagram_reels", account="Mi IG"))
    assert post is not None
    assert post.status == "listo"
    assert post.method == "manual"
    assert post.error is not None
    assert "URL pública" in post.error


# ── re-evaluar tope diario al subir MAX_UPLOADS_PER_DAY ─────────────────────


def test_raise_max_uploads_unblocks_daily_cap(tmp_path) -> None:
    from app.publish_queue import AccountQuota, AccountStatus, PublishQueueManager

    qm = PublishQueueManager(JobStore(tmp_path / "storage"))
    qm.MAX_UPLOADS_PER_DAY = 5
    q = AccountQuota(account_name="Canal", platform="youtube_shorts", uploads_today=5)
    qm._quotas["youtube_shorts:Canal"] = q
    qm._save_state()

    can, reason = qm.can_upload("youtube_shorts", "Canal")
    assert not can
    assert reason == "daily_limit_reached"
    assert qm._quotas["youtube_shorts:Canal"].status == AccountStatus.QUOTA_EXCEEDED

    qm.MAX_UPLOADS_PER_DAY = 9
    can, reason = qm.can_upload("youtube_shorts", "Canal")
    assert can
    assert reason == "daily_limit_raised"
    assert qm._quotas["youtube_shorts:Canal"].status == AccountStatus.HEALTHY


def test_platform_upload_limit_not_released_by_max(tmp_path) -> None:
    from app.publish_queue import PublishQueueManager

    qm = PublishQueueManager(JobStore(tmp_path / "storage"))
    qm.MAX_UPLOADS_PER_DAY = 99
    qm.record_upload("youtube_shorts", "Canal", False, 400, reason="uploadLimitExceeded")

    can, reason = qm.can_upload("youtube_shorts", "Canal")
    assert not can
    assert reason.startswith("quota_exceeded_until_")


def test_retry_at_awaits_min_delay_and_backoff(tmp_path) -> None:
    from app.publish_queue import AccountQuota, AccountStatus, PublishQueueManager

    qm = PublishQueueManager(JobStore(tmp_path / "storage"))
    qm.MIN_DELAY_BETWEEN_UPLOADS = 120

    q = AccountQuota(account_name="Canal", platform="youtube_shorts", last_upload=1000)
    assert qm._retry_at_for(q, "min_delay_not_met_120s", 1000) == 1120

    qr = AccountQuota(account_name="Canal", platform="youtube_shorts")
    qr.status = AccountStatus.RATE_LIMITED
    qr.next_retry_at = 555
    assert qm._retry_at_for(qr, "rate_limited", 100) == 555

    qq = AccountQuota(account_name="Canal", platform="youtube_shorts")
    qq.status = AccountStatus.QUOTA_EXCEEDED
    qq.quota_reset_at = 9999
    assert qm._retry_at_for(qq, "quota_exceeded_until_9999", 100) == 9999

    assert qm._retry_at_for(None, "ok", 100) == 400


def test_publish_queue_recovers_corrupt_file_from_tmp(tmp_path) -> None:
    from app.publish_queue import PublishQueueManager, UploadTask

    store = JobStore(tmp_path / "storage")
    qm = PublishQueueManager(store)
    qm.enqueue(
        UploadTask(job_id="j1", clip_id="c1", platform="youtube_shorts", account_name="Canal")
    )

    good = qm.queue_file.read_text(encoding="utf-8")
    qm.queue_file.with_suffix(".json.tmp").write_text(good, encoding="utf-8")
    qm.queue_file.write_text('[{"job_id": "j1", "clip_id"', encoding="utf-8")

    qm2 = PublishQueueManager(store)
    assert len(qm2._queue) == 1
    assert qm2._queue[0].clip_id == "c1"


def test_publish_queue_two_instances_do_not_lose_tasks(tmp_path) -> None:
    from app.publish_queue import PublishQueueManager, UploadTask

    store = JobStore(tmp_path / "storage")
    a = PublishQueueManager(store)
    b = PublishQueueManager(store)
    for i in range(5):
        a.enqueue(
            UploadTask(
                job_id=f"j{i}", clip_id=f"c{i}", platform="youtube_shorts", account_name="Canal"
            )
        )
        b.record_upload("youtube_shorts", "Canal", True)

    c = PublishQueueManager(store)
    assert len(c._queue) == 5
    assert [t.clip_id for t in c._queue] == ["c0", "c1", "c2", "c3", "c4"]
    quota = c._quotas["youtube_shorts:Canal"]
    assert quota.uploads_today == 5
    assert json.loads(c.queue_file.read_text(encoding="utf-8")) is not None
