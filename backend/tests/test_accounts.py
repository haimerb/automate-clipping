from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.transcriber import MockTranscriber


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "storage", MockTranscriber()))


def _register(client: TestClient, email: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/register", json={"email": email, "password": "clave123", "name": "Cuentista"}
    )
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_account_crud(tmp_path) -> None:
    client = _client(tmp_path)
    headers = _register(client, "cuentas@test.dev")

    body = {
        "platform": "youtube",
        "name": "Mi canal",
        "handle": "@micanal",
        "token": "tok-1",
        "client_id": "client-id-1",
        "client_secret": "super-secreto",
        "redirect_uri": "http://localhost:8000/api/youtube/callback",
    }
    resp = client.post("/api/accounts", json=body, headers=headers)
    assert resp.status_code == 201
    account = resp.json()
    assert account["name"] == "Mi canal"
    assert account["handle"] == "@micanal"
    assert account["client_id"] == "client-id-1"
    assert account["has_client_secret"] is True
    assert "client_secret" not in account
    account_id = account["id"]

    listed = client.get("/api/accounts", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["has_client_secret"] is True
    assert "client_secret" not in listed[0]

    updated = client.patch(
        f"/api/accounts/{account_id}",
        json={**body, "name": "Canal nuevo", "token": None, "client_secret": None},
        headers=headers,
    ).json()
    assert updated["name"] == "Canal nuevo"
    assert updated["token"] is None
    assert updated["has_client_secret"] is True

    dash = client.get("/api/dashboard", headers=headers).json()
    assert dash["accounts"] == 1

    assert client.delete(f"/api/accounts/{account_id}", headers=headers).status_code == 204
    assert client.get("/api/accounts", headers=headers).json() == []


def test_account_isolation_and_validation(tmp_path) -> None:
    client = _client(tmp_path)
    alice = _register(client, "alice@test.dev")
    bob = _register(client, "bob@test.dev")

    resp = client.post(
        "/api/accounts", json={"platform": "tiktok", "name": "De Alice"}, headers=alice
    )
    assert resp.status_code == 201
    account_id = resp.json()["id"]

    assert client.get(f"/api/accounts/{account_id}", headers=bob).status_code == 404
    assert (
        client.patch(
            f"/api/accounts/{account_id}",
            json={"platform": "tiktok", "name": "Robo"},
            headers=bob,
        ).status_code
        == 404
    )
    assert client.delete(f"/api/accounts/{account_id}", headers=bob).status_code == 404

    assert client.get("/api/accounts", headers=bob).json() == []
