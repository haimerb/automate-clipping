from __future__ import annotations

import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.branding import generate_avatar, generate_banner
from app.main import create_app

BG_UPSCALE = 800


class _FakeResp:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


def _png_bytes(size: tuple[int, int] = (64, 64), color=(30, 58, 138)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def no_net(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fuerza el fallback a gradiente: la descarga de fondo siempre falla."""
    def boom(*args, **kwargs):
        raise RuntimeError("sin red (test)")

    monkeypatch.setattr("app.branding._fetch_banner_background", boom)


@pytest.fixture
def fake_net(monkeypatch: pytest.MonkeyPatch) -> None:
    """Descarga de fondo simulada: ya descargada, guarda un PNG válido."""

    def fake_fetch(bg: str, dest) -> Path:
        from pathlib import Path
        Path(dest).write_bytes(_png_bytes())
        return Path(dest)

    monkeypatch.setattr("app.branding._fetch_banner_background", fake_fetch)


def _client(tmp_path) -> tuple[TestClient, dict[str, str]]:
    app = create_app(str(tmp_path / "store"))
    client = TestClient(app)
    resp = client.post(
        "/api/auth/register",
        json={"email": "brand@test.dev", "password": "secret123", "name": "B"},
    )
    if resp.status_code == 409:
        resp = client.post(
            "/api/auth/login",
            json={"email": "brand@test.dev", "password": "secret123"},
        )
    assert resp.status_code in (200, 201), resp.text
    token = resp.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


# ── módulo ────────────────────────────────────────────

def test_generate_banner_fallback_gradient(tmp_path, no_net):
    out = tmp_path / "banner.png"
    generate_banner(out, "FUTBOL VIRAL EDITS", "Resúmenes virales de fútbol", background_url=None)
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (2560, 1440)


def test_generate_avatar(tmp_path):
    out = tmp_path / "avatar.png"
    generate_avatar(out, "FUTBOL VIRAL EDITS")
    with Image.open(out) as im:
        assert im.size == (800, 800)


def test_detect_image_ext(tmp_path):
    import pytest as _pytest
    from app.branding import _detect_image_ext
    assert _detect_image_ext(b"\xff\xd8\xff\xe0") == ".jpg"
    assert _detect_image_ext(b"\x89PNG\r\n\x1a\n") == ".png"
    assert _detect_image_ext(b"RIFF\x00\x00\x00\x00WEBP") == ".webp"
    with _pytest.raises(RuntimeError):
        _detect_image_ext(b"<html>not an image</html>")


# ── endpoints ─────────────────────────────────────────

def test_branding_requires_auth(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/channel/branding")
    assert resp.status_code == 401


def test_branding_generate_and_serve(tmp_path, fake_net):
    client, headers = _client(tmp_path)
    resp = client.post(
        "/api/channel/branding",
        json={"channel_name": "FUTBOL VIRAL EDITS", "tagline": "Goles y más", "background_url": "https://x/img.png"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    info = resp.json()
    assert info["channel_name"] == "FUTBOL VIRAL EDITS"
    assert info["banner_exists"] is True
    assert info["avatar_exists"] is True

    banner = client.get("/api/channel/branding/banner", headers=headers)
    assert banner.status_code == 200
    assert banner.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(banner.content)) as im:
        assert im.size == (2560, 1440)

    avatar = client.get("/api/channel/branding/avatar", headers=headers)
    assert avatar.status_code == 200
    with Image.open(io.BytesIO(avatar.content)) as im:
        assert im.size == (800, 800)

    meta = client.get("/api/channel/branding", headers=headers)
    assert meta.status_code == 200
    assert meta.json()["tagline"] == "Goles y más"


def test_branding_fallback_sin_red(tmp_path, no_net):
    client, headers = _client(tmp_path)
    resp = client.post(
        "/api/channel/branding",
        json={"channel_name": "FUTBOL VIRAL EDITS", "background_url": None},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["banner_exists"] is True


def test_branding_aislamiento_entre_usuarios(tmp_path, fake_net):
    app = create_app(str(tmp_path / "store"))
    client = TestClient(app)
    a = client.post("/api/auth/register", json={"email": "a@test.dev", "password": "secret123", "name": "A"})
    b = client.post("/api/auth/register", json={"email": "b@test.dev", "password": "secret123", "name": "B"})
    h_a = {"Authorization": f"Bearer {a.json()['access_token']}"}
    h_b = {"Authorization": f"Bearer {b.json()['access_token']}"}

    assert client.post("/api/channel/branding", json={}, headers=h_a).status_code == 201
    # usuario B no ve las imágenes de A (404, no las genera)
    assert client.get("/api/channel/branding", headers=h_b).json()["banner_exists"] is False
    assert client.get("/api/channel/branding/banner", headers=h_b).status_code == 404