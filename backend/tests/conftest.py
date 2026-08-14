from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_db_dir = tempfile.mkdtemp(prefix="edgetape-test-db-")
# Fuerza SQLite ANTES de importar app: EDGETAPE_DATABASE_URL tiene prioridad sobre
# DATABASE_URL, así que se asigna directamente (no setdefault) para ganarle al .env.
os.environ["EDGETAPE_DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["DATABASE_URL"] = os.environ["EDGETAPE_DATABASE_URL"]
os.environ["EDGETAPE_JWT_SECRET"] = "edgetape-test-secret"

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def auth_headers() -> dict[str, str]:
    app = create_app(tempfile.mkdtemp(prefix="edgetape-test-store-"))
    client = TestClient(app)
    email = "test@edgetape.dev"
    password = "secret123"
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Tester"},
    )
    if resp.status_code == 409:
        resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code in (200, 201), resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def user_id(auth_headers: dict[str, str]) -> str:
    app = create_app(tempfile.mkdtemp(prefix="edgetape-test-store-"))
    client = TestClient(app)
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]
