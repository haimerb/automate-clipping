from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from unittest import mock

from app.transcriber import GroqWhisperTranscriber


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "text": "hola",
            "segments": [{"start": 0.0, "end": 2.5, "text": "hola"}],
        }


@pytest.fixture(scope="module")
def long_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    src = tmp_path_factory.mktemp("groq") / "video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=duration=600:size=360x640:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=600",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(src),
        ],
        check=True, capture_output=True,
    )
    return src


def test_groq_splits_long_audio_into_chunks(long_video: Path) -> None:
    """Un video de 10 min debe partirse en chunks <=8 min con offsets re-encadenados
    (Groq rechaza con 413 el audio >25 MB)."""
    t = GroqWhisperTranscriber(api_key="test-key")
    posted: list[str] = []

    def fake_post(url: str, headers: dict, files: dict, data: dict, timeout: float):
        assert data["model"].startswith("whisper"), data["model"]
        posted.append(files["file"][0])
        return _FakeResponse()

    with mock.patch("httpx.post", side_effect=fake_post):
        segs = t.transcribe(str(long_video), duration=600.0)

    assert len(posted) >= 2, f"se esperaban varios chunks, subidos: {posted}"
    assert posted[0].endswith(".wav")
    starts = sorted(s["start"] for s in segs)
    assert starts[0] == 0.0
    assert starts[-1] >= 480.0, starts[-1]
    for s in segs:
        assert s["end"] > s["start"]


def test_groq_single_chunk_no_offset(long_video: Path) -> None:
    """Un audio corto (menos de un chunk) no debe aplicar offset."""
    t = GroqWhisperTranscriber(api_key="test-key")

    with mock.patch("httpx.post", return_value=_FakeResponse()) as op:
        segs = t.transcribe(str(long_video), duration=120.0)

    assert op.call_count == 1
    assert segs == [{"start": 0.0, "end": 2.5, "text": "hola"}]


def test_groq_retries_on_429_then_succeeds(long_video: Path) -> None:
    """El rate limit (429) de Groq debe reintentar con backoff y responder OK."""
    t = GroqWhisperTranscriber(api_key="test-key")
    calls = {"n": 0}

    def fake_post(url: str, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            r = _FakeResponse()
            r.status_code = 429
            return r
        return _FakeResponse()

    with mock.patch("httpx.post", side_effect=fake_post):
        segs = t.transcribe(str(long_video), duration=120.0)

    assert calls["n"] == 2
    assert segs and segs[0]["text"] == "hola"