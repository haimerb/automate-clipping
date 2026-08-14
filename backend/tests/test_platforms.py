from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Clip
from app.storage import JobStore
from app.transcriber import MockTranscriber


def test_platform_crud_and_dashboard(tmp_path, auth_headers, user_id) -> None:
    storage = tmp_path / "storage"
    store = JobStore(storage)
    app = create_app(storage, MockTranscriber())
    client = TestClient(app)

    job = store.create_job("video.mp4", owner_id=user_id)
    store.save_clips(
        job.id,
        [
            Clip(
                id="c1",
                index=1,
                start=0,
                end=10,
                duration=10,
                title="El momento clave",
                line="esto es importante",
                script="esto es importante",
                score=1.0,
            )
        ],
    )

    assert client.get("/api/dashboard", headers=auth_headers).json()["posts"] == 0

    body = {
        "platform": "tiktok",
        "status": "publicado",
        "url": "https://tiktok.com/@x/video/1",
        "views": 1200,
        "likes": 80,
        "earnings": 3.5,
        "currency": "USD",
    }
    resp = client.post(f"/api/jobs/{job.id}/clips/c1/platforms", json=body, headers=auth_headers)
    assert resp.status_code == 201
    post = resp.json()
    assert post["platform"] == "tiktok"
    assert post["clip_id"] == "c1"
    post_id = post["id"]

    listed = client.get(f"/api/jobs/{job.id}/platforms", headers=auth_headers).json()
    assert len(listed) == 1

    dash = client.get("/api/dashboard", headers=auth_headers).json()
    assert dash["posts"] == 1
    assert dash["publicados"] == 1
    assert dash["total_views"] == 1200
    assert dash["total_earnings"] == 3.5
    assert dash["by_platform"]["tiktok"]["earnings"] == 3.5
    assert dash["recent_posts"][0]["title"] == "El momento clave"

    updated = client.patch(
        f"/api/jobs/{job.id}/platforms/{post_id}",
        json={**body, "views": 2000, "earnings": 7.0},
        headers=auth_headers,
    ).json()
    assert updated["views"] == 2000
    assert updated["earnings"] == 7.0

    assert (
        client.delete(f"/api/jobs/{job.id}/platforms/{post_id}", headers=auth_headers).status_code
        == 204
    )
    assert client.get("/api/dashboard", headers=auth_headers).json()["posts"] == 0


def test_platform_validation(tmp_path, auth_headers, user_id) -> None:
    storage = tmp_path / "storage"
    app = create_app(storage, MockTranscriber())
    client = TestClient(app)

    job = JobStore(storage).create_job("video.mp4", owner_id=user_id)

    bad = client.post(
        f"/api/jobs/{job.id}/clips/nope/platforms", json={"platform": "tiktok"}, headers=auth_headers
    )
    assert bad.status_code == 404

    bad_clip = client.post(
        "/api/jobs/does-not-exist/clips/c1/platforms",
        json={"platform": "tiktok"},
        headers=auth_headers,
    )
    assert bad_clip.status_code == 404

    assert (
        client.patch(
            f"/api/jobs/{job.id}/platforms/nope", json={"platform": "x"}, headers=auth_headers
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/jobs/{job.id}/platforms/nope", headers=auth_headers).status_code == 404
    )


def test_job_owner_isolation(tmp_path, auth_headers, user_id) -> None:
    storage = tmp_path / "storage"
    app = create_app(storage, MockTranscriber())
    client = TestClient(app)
    store = JobStore(storage)

    mine = store.create_job("mi-video.mp4", owner_id=user_id)
    theirs = store.create_job("video-ajeno.mp4", owner_id="otro-usuario")

    assert client.get(f"/api/jobs/{mine.id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/jobs/{theirs.id}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/jobs/{mine.id}/clips", headers=auth_headers).status_code == 200
    assert client.get(f"/api/jobs/{theirs.id}/clips", headers=auth_headers).status_code == 404


def test_list_jobs_endpoint(tmp_path, auth_headers, user_id) -> None:
    storage = tmp_path / "storage"
    app = create_app(storage, MockTranscriber())
    client = TestClient(app)
    store = JobStore(storage)

    store.create_job("primero.mp4", owner_id=user_id)
    store.create_job("segundo.mp4", owner_id=user_id)
    store.create_job("ajeno.mp4", owner_id="otro-usuario")

    assert client.get("/api/jobs", headers=auth_headers).status_code == 200
    jobs = client.get("/api/jobs", headers=auth_headers).json()
    assert [j["filename"] for j in jobs] == ["segundo.mp4", "primero.mp4"]
    assert client.get("/api/jobs").status_code == 401


def test_unauthorized_requests(tmp_path, user_id) -> None:
    app = create_app(tmp_path / "storage", MockTranscriber())
    client = TestClient(app)
    store = JobStore(tmp_path / "storage")
    job = store.create_job("video.mp4", owner_id=user_id)

    assert client.get("/api/dashboard").status_code == 401
    assert client.get(f"/api/jobs/{job.id}").status_code == 401
    assert client.get(f"/api/jobs/{job.id}/clips").status_code == 401
    assert client.post("/api/accounts", json={"platform": "tiktok", "name": "x"}).status_code == 401
