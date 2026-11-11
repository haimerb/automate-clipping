from __future__ import annotations

import base64
import sys
import types
from pathlib import Path

import pytest

from app.providers import images, video

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n0kAAAAASUVORK5CYII="
) + b"\0" * 2048


class _FakeResponse:
    status_code = 200
    headers = {"content-type": "image/png"}
    content = _PNG
    text = ""

    def json(self):
        return {}


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        return _FakeResponse()


def _cloudflare_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EDGETAPE_IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setenv("EDGETAPE_CLOUDFLARE_ACCOUNT_ID", "acc")
    monkeypatch.setenv("EDGETAPE_CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("EDGETAPE_IMAGE_DAILY_LIMIT", "10")
    monkeypatch.setenv("EDGETAPE_QUOTA_FILE", str(tmp_path / "quota.json"))


def test_cloudflare_generate_image_writes_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cloudflare_env(monkeypatch, tmp_path)
    monkeypatch.setattr(images.httpx, "Client", _FakeClient)

    path = images.generate_image("Boca Juniors", (1080, 1920), tmp_path / "scene")

    assert path is not None and path.exists()
    assert path.read_bytes() == _PNG


def test_cloudflare_requires_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_IMAGE_PROVIDER", "cloudflare")
    monkeypatch.delenv("EDGETAPE_CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("EDGETAPE_CLOUDFLARE_API_TOKEN", raising=False)
    assert images.is_configured() is False
    assert images.generate_image("x", (1080, 1920), tmp_path / "x") is None


def test_cloudflare_respects_daily_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cloudflare_env(monkeypatch, tmp_path)
    monkeypatch.setenv("EDGETAPE_IMAGE_DAILY_LIMIT", "0")
    monkeypatch.setattr(images.httpx, "Client", _FakeClient)
    assert images.generate_image("x", (1080, 1920), tmp_path / "x") is None


def test_hf_image_to_video_copies_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_VIDEO_PROVIDER", "hf")
    monkeypatch.setenv("EDGETAPE_HF_TOKEN", "tok")
    monkeypatch.setenv("EDGETAPE_HF_VIDEO_DAILY", "10")
    monkeypatch.setenv("EDGETAPE_QUOTA_FILE", str(tmp_path / "quota.json"))

    generated = tmp_path / "generated.mp4"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def predict(self, **kwargs):
            generated.write_bytes(b"v" * 4096)
            return {"video": str(generated)}

    fake = types.ModuleType("gradio_client")
    fake.Client = _Client
    fake.handle_file = lambda p: p
    monkeypatch.setitem(sys.modules, "gradio_client", fake)

    out = video.image_to_video(tmp_path / "still.jpg", "animate", tmp_path / "hero.mp4")

    assert out is not None and out.exists()
    assert out.read_bytes() == b"v" * 4096


def test_hf_video_provider_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_VIDEO_PROVIDER", "off")
    monkeypatch.setenv("EDGETAPE_HF_TOKEN", "tok")
    assert video.is_configured() is False
    assert video.image_to_video(tmp_path / "x", "p", tmp_path / "y") is None


def test_result_path_accepts_nested_shapes(tmp_path: Path) -> None:
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    assert video._result_path({"video": str(f)}) == f
    assert video._result_path((None, {"path": str(f)})) == f
    assert video._result_path("no-existe") is None
