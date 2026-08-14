from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.youtube import download_youtube, is_youtube_url


def _install_fake_ytdlp(tmp_path, title="Como triunfar en 2026", writes=True):
    calls: dict = {}

    class FakeYDL:
        def __init__(self, opts):
            calls["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            calls["url"] = url
            calls["download"] = download
            if writes:
                (tmp_path / "source.mp4").write_bytes(b"\x00" * 1024)
                (tmp_path / "source.webm").write_bytes(b"\x00" * 512)
            return {"title": title}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    sys.modules["yt_dlp"] = fake
    return calls


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    sys.modules.pop("yt_dlp", None)


def test_is_youtube_url() -> None:
    assert is_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert is_youtube_url("https://youtu.be/abc123")
    assert not is_youtube_url("https://vimeo.com/123")
    assert not is_youtube_url("mi_video.mp4")


def test_download_youtube_picks_largest_file(tmp_path) -> None:
    calls = _install_fake_ytdlp(tmp_path)
    path, title = asyncio.run(
        download_youtube("https://youtu.be/abc", tmp_path / "source")
    )
    assert path.endswith("source.mp4")
    assert title == "Como triunfar en 2026"
    assert calls["url"] == "https://youtu.be/abc"
    assert calls["download"] is True
    assert "noplaylist" in calls["opts"]
    assert calls["opts"]["format"] == "bv*+ba/b"
    assert "User-Agent" in calls["opts"]["http_headers"]


def test_download_youtube_raises_when_nothing_downloaded(tmp_path) -> None:
    _install_fake_ytdlp(tmp_path, writes=False)
    with pytest.raises(RuntimeError):
        asyncio.run(download_youtube("https://youtu.be/abc", tmp_path / "source"))


def test_download_youtube_retries_and_ignores_partial_files(tmp_path) -> None:
    attempts: list[dict] = []

    class FakeYDL:
        def __init__(self, opts):
            attempts.append(opts.get("extractor_args", {}))
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            if len(attempts) == 1:
                (tmp_path / "source.mp4.part").write_bytes(b"\x00" * 5000)
                raise RuntimeError("HTTP Error 403: Forbidden")
            (tmp_path / "source.webm").write_bytes(b"\x00" * 1024)
            (tmp_path / "source.mp4").write_bytes(b"\x00" * 2048)
            return {"title": "ok"}

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYDL
    sys.modules["yt_dlp"] = fake

    path, title = asyncio.run(
        download_youtube("https://youtu.be/abc", tmp_path / "source")
    )
    assert path.endswith("source.mp4")
    assert title == "ok"
    assert len(attempts) == 2
    assert attempts[0], "el primer intento debe usar extractor_args de cliente"
    assert "player_client" in attempts[0]["youtube"]
