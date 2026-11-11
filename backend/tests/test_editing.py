from __future__ import annotations

from pathlib import Path

import pytest

from app import ai_generate as aig


def test_caption_text_keeps_short_phrase_whole() -> None:
    assert aig._caption_text("Primero pregunta, después ofrece.") == "Primero pregunta, después ofrece."


def test_caption_text_truncates_long_clause() -> None:
    text = (
        "Una primera cláusula larguísima que no cabe en el cartel de ninguna "
        "manera posible y que además sigue creciendo"
    )
    out = aig._caption_text(text, max_chars=60)
    assert out.endswith("…")
    assert len(out) <= 61


def test_caption_text_empty() -> None:
    assert aig._caption_text("   ") == ""


def test_render_segment_video_has_no_hflip_or_fades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, timeout=600):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")

    monkeypatch.setattr(aig, "_run_ffmpeg", _fake_run)
    aig._render_segment_video(Path("clip.mp4"), 4.0, 1, (1080, 1920), tmp_path / "seg.mp4")

    joined = " ".join(calls[0])
    assert "hflip" not in joined
    assert "fade=" not in joined
    assert "eq=" in joined


def test_render_segment_has_no_fade_to_black(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, timeout=600):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")

    monkeypatch.setattr(aig, "_run_ffmpeg", _fake_run)
    aig._render_segment(tmp_path / "still.png", 4.0, 0, (1080, 1920), tmp_path / "seg.mp4")

    joined = " ".join(calls[0])
    assert "fade=" not in joined
    assert "eq=" in joined


def test_grade_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_GRADE", "off")
    calls: list[list[str]] = []

    def _fake_run(cmd, timeout=600):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")

    monkeypatch.setattr(aig, "_run_ffmpeg", _fake_run)
    aig._render_segment_video(Path("clip.mp4"), 4.0, 1, (1080, 1920), tmp_path / "seg.mp4")
    assert "eq=" not in " ".join(calls[0])


def test_captions_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_SUBTITLE_MODE", "none")
    assert aig._render_captions(["Uno dos tres.", "Cuatro cinco seis."], (1080, 1920), tmp_path) == [None, None]


def test_mix_music_uses_ducking_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, timeout=600):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")

    monkeypatch.setattr(aig, "_run_ffmpeg", _fake_run)
    out = aig._mix_music("voice.m4a", 10.0, Path("music.mp3"), tmp_path / "mix.m4a")

    assert out == str(tmp_path / "mix.m4a")
    joined = " ".join(calls[0])
    assert "sidechaincompress" in joined
    assert "amix" in joined
