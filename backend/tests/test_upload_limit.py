from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import create_app
from app.transcriber import MockTranscriber


def _registered_client(tmp_path) -> TestClient:
    client = TestClient(create_app(tmp_path / "storage", MockTranscriber()))
    email = f"{uuid.uuid4().hex[:10]}@test.dev"
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "clave123", "name": "Up"},
    )
    assert resp.status_code in (200, 201), resp.text
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client


def test_upload_over_limit_is_rejected_and_cleaned(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDGETAPE_MAX_UPLOAD_BYTES", "512")
    client = _registered_client(tmp_path)

    payload = b"x" * 4096
    resp = client.post(
        "/api/jobs",
        files={"file": ("grande.mp4", payload, "video/mp4")},
    )

    assert resp.status_code == 413
    storage = tmp_path / "storage"
    assert list(storage.iterdir()) == [], "el job parcial debe borrarse al rechazar"


def test_upload_within_limit_is_accepted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EDGETAPE_MAX_UPLOAD_BYTES", str(4 * 1024 * 1024))
    client = _registered_client(tmp_path)

    payload = b"x" * 1024
    resp = client.post(
        "/api/jobs",
        files={"file": ("pequeno.mp4", payload, "video/mp4")},
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["filename"] == "pequeno.mp4"
