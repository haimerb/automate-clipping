from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app import narration

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg required",
)


def _fake_voice(text: str, voice: str | None, out: Path) -> str:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2",
            "-ar", "48000", "-ac", "1", str(out),
        ],
        check=True,
    )
    return str(out)


def test_build_narration_uses_real_sentence_durations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_TTS_PROVIDER", "auto")
    monkeypatch.setenv("EDGETAPE_TTS_PAUSE_MS", "200")
    monkeypatch.setattr("app.ai_generate.build_voiceover", _fake_voice)

    sentences = ["Hola mundo.", "Segunda oración."]
    n = narration.build_narration(sentences, "es-MX-DaliaNeural", tmp_path)

    assert n.audio and Path(n.audio).exists()
    assert len(n.starts) == len(n.ends) == len(n.durations) == 2
    assert n.durations == pytest.approx([1.2, 1.2], abs=0.12)
    # 1.2 + pausa + 1.2 + pausa
    assert 2.6 <= n.total <= 3.1
    assert n.starts == sorted(n.starts)
    assert n.ends[-1] == pytest.approx(n.total, abs=0.01)
    assert n.starts[1] == pytest.approx(n.ends[0], abs=0.01)
    assert n.provider in {"edge", "gtts"}
    assert not n.warnings or all("gTTS" in w or "TTS" in w for w in n.warnings)


def test_build_narration_without_tts_returns_no_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_TTS_PROVIDER", "auto")
    monkeypatch.setattr("app.ai_generate.build_voiceover", lambda *a, **k: None)

    n = narration.build_narration(["Hola mundo.", "Otra frase."], "es-MX-DaliaNeural", tmp_path)

    assert n.audio is None
    assert n.warnings
    assert any("ninguna oración" in w for w in n.warnings)


def test_build_narration_provider_none_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_TTS_PROVIDER", "none")
    n = narration.build_narration(["Hola mundo."], "es-MX-DaliaNeural", tmp_path)
    assert n.audio is None
    assert n.provider == "none"
    assert any("desactivado" in w for w in n.warnings)
