from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.transcriber import MockTranscriber


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "storage", MockTranscriber()))


def test_register_and_login(tmp_path) -> None:
    client = _client(tmp_path)

    resp = client.post(
        "/api/auth/register",
        json={"email": "nueva@test.dev", "password": "clave123", "name": "Nueva"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == "nueva@test.dev"
    assert body["user"]["name"] == "Nueva"

    login = client.post(
        "/api/auth/login", json={"email": "nueva@test.dev", "password": "clave123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "nueva@test.dev"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_register_validation(tmp_path) -> None:
    client = _client(tmp_path)

    assert (
        client.post("/api/auth/register", json={"email": "raro", "password": "clave123"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/register", json={"email": "corta@test.dev", "password": "123"}
        ).status_code
        == 422
    )

    first = client.post(
        "/api/auth/register", json={"email": "dup@test.dev", "password": "clave123"}
    )
    assert first.status_code == 201
    assert (
        client.post(
            "/api/auth/register", json={"email": "DUP@test.dev", "password": "clave123"}
        ).status_code
        == 409
    )


def test_login_failures(tmp_path) -> None:
    client = _client(tmp_path)

    assert client.post("/api/auth/login", json={"email": "x@y.com", "password": "nope"}).status_code == 401

    client.post("/api/auth/register", json={"email": "ok@test.dev", "password": "clave123"})
    assert (
        client.post("/api/auth/login", json={"email": "ok@test.dev", "password": "incorrecta"}).status_code
        == 401
    )


def test_me_requires_token(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer basura"}).status_code == 401
