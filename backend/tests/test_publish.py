from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import publish as pubmod
from app import youtube_publish as ytpub
from app.main import create_app
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
            "-f", "lavfi", "-i", "testsrc2=duration=60:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def _done_job(tmp_path: Path, auth_headers: dict, sample_video: Path) -> tuple[TestClient, JobStore, str]:
    storage = tmp_path / "storage"
    transcriber = MockTranscriber()
    app = create_app(storage, transcriber)
    client = TestClient(app)
    store = JobStore(storage)
    for _ in range(5):
        with sample_video.open("rb") as fh:
            resp = client.post(
                "/api/jobs", files={"file": ("sample.mp4", fh, "video/mp4")}, headers=auth_headers
            )
        assert resp.status_code == 202
        job_id = resp.json()["id"]
        asyncio.run(run_job(job_id, store, transcriber))
        if store.get_clips(job_id):
            assert store.get_job(job_id).status == "done"
            return client, store, job_id
    raise AssertionError("no se generaron clips en ningún intento")


def test_publish_fallback_creates_ready_post(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_real_upload(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_real_upload_env_fallback(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_api_key_token_falls_back(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_skips_when_already_published(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
    client.post(
        "/api/accounts",
        json={"platform": "youtube", "name": "Canal Duplicado", "handle": "@x", "token": "RT-DUP"},
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
    assert second is None


def test_publish_all_only_marked_clips(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_all_endpoint(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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
    posts = resp.json()
    assert len(posts) == 1
    assert posts[0]["status"] == "listo"
    assert posts[0]["url"] == pubmod.STUDIO_UPLOAD_URL


def test_publish_clip_endpoint(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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
    tmp_path, auth_headers, sample_video, monkeypatch
) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
    clip_id = store.get_clips(job_id)[0].id

    first = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "tiktok"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/jobs/{job_id}/clips/{clip_id}/publish",
        json={"platform": "tiktok"},
        headers=auth_headers,
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


def test_publish_clip_resolves_account_by_platform(
    tmp_path, auth_headers, sample_video, monkeypatch
) -> None:
    monkeypatch.setattr(ytpub, "is_configured", lambda: False)
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_publish_clip_endpoint_requires_done_job(tmp_path, auth_headers, sample_video) -> None:
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


def test_patch_job_settings_auto_publish(tmp_path, auth_headers, sample_video) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
    resp = client.patch(f"/api/jobs/{job_id}", json={"auto_publish": True}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["auto_publish"] is True
    assert store.get_job(job_id).auto_publish is True


def test_clip_thumbnail(tmp_path, auth_headers, auth_token, sample_video) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_youtube_auth_url_builds_link(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_youtube_auth_url_requires_credentials(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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


def test_youtube_callback_stores_refresh_token(tmp_path, auth_headers, sample_video, monkeypatch) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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
    tmp_path, auth_headers, sample_video, monkeypatch
) -> None:
    client, store, job_id = _done_job(tmp_path, auth_headers, sample_video)
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
