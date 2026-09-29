from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import meta_publish as metapub
from app import tiktok_publish as tiktok
from app.auth import media_token, verify_media_token
from app.main import create_app
from app.models import Clip
from app.storage import JobStore
from app.transcriber import MockTranscriber


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "storage", MockTranscriber()))


def _account(client: TestClient, headers: dict, platform: str, **extra) -> dict:
    body = {"platform": platform, "name": f"cuenta {platform}", "handle": "", "token": None, **extra}
    resp = client.post("/api/accounts", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _saved(client: TestClient, headers: dict, account_id: str) -> dict:
    return next(a for a in client.get("/api/accounts", headers=headers).json() if a["id"] == account_id)


# ── TikTok ───────────────────────────────────────────────────


def test_tiktok_auth_url_requires_creds(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EDGETAPE_TIKTOK_CLIENT_KEY", raising=False)
    monkeypatch.delenv("EDGETAPE_TIKTOK_CLIENT_SECRET", raising=False)
    client = _client(tmp_path)
    account = _account(client, auth_headers, "tiktok")
    resp = client.get(f"/api/accounts/{account['id']}/tiktok/auth", headers=auth_headers)
    assert resp.status_code == 400
    assert "client_key" in resp.json()["detail"]


def test_tiktok_auth_url_uses_account_creds(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(
        client, auth_headers, "tiktok", client_id="key-123", client_secret="sec-123"
    )
    resp = client.get(f"/api/accounts/{account['id']}/tiktok/auth", headers=auth_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["auth_url"].startswith(tiktok.AUTH_URL)
    assert "client_key=key-123" in payload["auth_url"]
    assert "scope=video.upload%2Cvideo.publish" in payload["auth_url"]
    assert f"state={account['id']}" in payload["auth_url"]
    assert payload["redirect_uri"].endswith("/api/tiktok/callback")


def test_tiktok_auth_rejects_other_platform(
    tmp_path: Path, auth_headers: dict
) -> None:
    client = _client(tmp_path)
    account = _account(client, auth_headers, "youtube", client_id="a", client_secret="b")
    resp = client.get(f"/api/accounts/{account['id']}/tiktok/auth", headers=auth_headers)
    assert resp.status_code == 400


def test_tiktok_callback_stores_refresh_token(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(
        client, auth_headers, "tiktok", client_id="key-123", client_secret="sec-123"
    )

    def _fake_exchange(code, creds, c=None):
        assert code == "code-abc"
        return {"access_token": "at", "refresh_token": "rt-999", "expires_in": 86400}

    monkeypatch.setattr("app.tiktok_publish.exchange_code", _fake_exchange)
    resp = client.get(
        f"/api/tiktok/callback?code=code-abc&state={account['id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/?tiktok=connected"

    assert _saved(client, auth_headers, account["id"])["token"] == "rt-999"


def test_tiktok_callback_without_token_redirects_error(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(
        client, auth_headers, "tiktok", client_id="key-123", client_secret="sec-123"
    )
    monkeypatch.setattr("app.tiktok_publish.exchange_code", lambda *a, **k: {})
    resp = client.get(
        f"/api/tiktok/callback?code=x&state={account['id']}", follow_redirects=False
    )
    assert resp.headers["location"] == "/?tiktok=error"


def test_tiktok_default_privacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDGETAPE_TIKTOK_PRIVACY", raising=False)
    assert tiktok.default_privacy() == "SELF_ONLY"
    monkeypatch.setenv("EDGETAPE_TIKTOK_PRIVACY", "public_to_everyone")
    assert tiktok.default_privacy() == "PUBLIC_TO_EVERYONE"
    monkeypatch.setenv("EDGETAPE_TIKTOK_PRIVACY", "inventado")
    assert tiktok.default_privacy() == "SELF_ONLY"


def test_tiktok_init_sends_caption_and_privacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El caption (título + descripción) y la privacidad llegan al init de TikTok."""
    seen: dict = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": {"publish_id": "p1", "upload_url": "http://up"}}

    class _Client:
        def post(self, url, json=None, headers=None):
            seen["url"] = url
            seen["body"] = json
            return _Resp()

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"0" * 2048)
    tiktok._init_upload(
        str(source), "at", tiktok.TiktokCreds("k", "s", "http://cb"), _Client(),
        caption="Mi título\n#viral",
    )
    info = seen["body"]["post_info"]
    assert info["title"] == "Mi título\n#viral"
    assert info["privacy_level"] == "SELF_ONLY"


# ── Meta (Facebook / Instagram) ──────────────────────────────


def test_meta_auth_url_requires_creds(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EDGETAPE_META_CLIENT_ID", raising=False)
    monkeypatch.delenv("EDGETAPE_META_CLIENT_SECRET", raising=False)
    client = _client(tmp_path)
    account = _account(client, auth_headers, "facebook")
    resp = client.get(f"/api/accounts/{account['id']}/meta/auth", headers=auth_headers)
    assert resp.status_code == 400
    assert "Meta" in resp.json()["detail"]


def test_meta_auth_url_uses_account_creds(
    tmp_path: Path, auth_headers: dict
) -> None:
    client = _client(tmp_path)
    account = _account(
        client, auth_headers, "instagram", client_id="meta-1", client_secret="meta-secret"
    )
    payload = client.get(
        f"/api/accounts/{account['id']}/meta/auth", headers=auth_headers
    ).json()
    assert "client_id=meta-1" in payload["auth_url"]
    assert "pages_show_list" in payload["auth_url"]
    assert "instagram_content_publish" in payload["auth_url"]
    assert payload["redirect_uri"].endswith("/api/meta/callback")


def test_meta_callback_links_page_for_facebook(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(
        client, auth_headers, "facebook", client_id="m", client_secret="s"
    )
    monkeypatch.setattr("app.meta_publish.exchange_code", lambda *a, **k: "user-token")
    monkeypatch.setattr(
        "app.meta_publish.list_targets",
        lambda *a, **k: [
            {
                "page_id": "page-1", "page_name": "Mi Página", "page_token": "page-token",
                "ig_user_id": "ig-1", "ig_username": "mifoto",
            }
        ],
    )
    resp = client.get(
        f"/api/meta/callback?code=c&state={account['id']}", follow_redirects=False
    )
    assert resp.headers["location"] == "/?meta=connected"
    saved = _saved(client, auth_headers, account["id"])
    assert saved["handle"] == "page-1"
    assert saved["name"] == "Mi Página"
    assert saved["token"] == "page-token"


def test_meta_callback_links_instagram_business(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(client, auth_headers, "instagram", client_id="m", client_secret="s")
    monkeypatch.setattr("app.meta_publish.exchange_code", lambda *a, **k: "user-token")
    monkeypatch.setattr(
        "app.meta_publish.list_targets",
        lambda *a, **k: [
            {
                "page_id": "page-1", "page_name": "Página", "page_token": "page-token",
                "ig_user_id": "ig-42", "ig_username": "mifoto",
            }
        ],
    )
    resp = client.get(
        f"/api/meta/callback?code=c&state={account['id']}", follow_redirects=False
    )
    assert resp.headers["location"] == "/?meta=connected"
    saved = _saved(client, auth_headers, account["id"])
    assert saved["handle"] == "ig-42"
    assert saved["name"] == "@mifoto"


def test_meta_callback_without_instagram_business(
    tmp_path: Path, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)
    account = _account(client, auth_headers, "instagram", client_id="m", client_secret="s")
    monkeypatch.setattr("app.meta_publish.exchange_code", lambda *a, **k: "user-token")
    monkeypatch.setattr(
        "app.meta_publish.list_targets",
        lambda *a, **k: [
            {
                "page_id": "p", "page_name": "P", "page_token": "t",
                "ig_user_id": "", "ig_username": "",
            }
        ],
    )
    resp = client.get(
        f"/api/meta/callback?code=c&state={account['id']}", follow_redirects=False
    )
    assert resp.headers["location"] == "/?meta=no_instagram"


def test_meta_list_targets_parses_pages() -> None:
    """El parseo de /me/accounts ignora páginas sin token."""
    payload = {
        "data": [
            {
                "id": "111", "name": "Página 1", "access_token": "tok-1",
                "instagram_business_account": {"id": "ig-1", "username": "foto"},
            },
            {"id": "222", "name": "Página 2", "access_token": ""},
        ]
    }

    class _Resp:
        text = "{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class _Client:
        def request(self, method, url, **kwargs):
            return _Resp()

    targets = metapub.list_targets("user-token", client=_Client())
    assert targets == [
        {
            "page_id": "111", "page_name": "Página 1", "page_token": "tok-1",
            "ig_user_id": "ig-1", "ig_username": "foto",
        }
    ]


# ── media firmada (Instagram necesita URL pública) ────────────


def test_media_token_roundtrip() -> None:
    token = media_token("clip", "job1", "c1")
    assert verify_media_token(token, "clip", "job1", "c1")
    assert not verify_media_token(token, "clip", "job1", "c2")
    assert not verify_media_token("nope", "clip", "job1", "c1")


def test_public_clip_url_requires_base(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import publish as pub

    monkeypatch.delenv("EDGETAPE_PUBLIC_BASE_URL", raising=False)
    assert pub.public_clip_url("j1", "c1") is None
    monkeypatch.setenv("EDGETAPE_PUBLIC_BASE_URL", "https://space.hf.space/")
    url = pub.public_clip_url("j1", "c1")
    assert url is not None and url.startswith("https://space.hf.space/api/public/clips/j1/c1/")
    assert url.endswith(".mp4")
    token = url.rsplit("/", 1)[-1].removesuffix(".mp4")
    assert verify_media_token(token, "clip", "j1", "c1")


def test_public_clip_route_requires_valid_signature(
    tmp_path: Path, auth_headers: dict, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    store = JobStore(storage)
    job = store.create_job("clip público", owner_id=user_id)
    exports = store.exports_dir(job.id)
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "c1_x.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 512)
    store.save_clips(job.id, [Clip(id="c1", index=1, start=0, end=2, duration=2,
                                   title="t", line="l", script="s", score=1.0, exported=True,
                                   export_name="c1_x.mp4")])
    client = TestClient(create_app(storage, MockTranscriber()))
    good = media_token("clip", job.id, "c1")
    assert client.get(f"/api/public/clips/{job.id}/c1/{good}.mp4").status_code == 200
    assert client.get(f"/api/public/clips/{job.id}/c1/xxx.mp4").status_code == 404
    assert client.get(f"/api/public/clips/{job.id}/c2/{good}.mp4").status_code == 404
