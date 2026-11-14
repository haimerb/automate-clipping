from __future__ import annotations

"""Narración por oración con duraciones reales.

El TTS anterior sintetizaba todo el guion en un solo archivo y repartía el
tiempo por número de palabras. Eso desincronizaba escenas y subtítulos y dejaba
silencio al final. Aquí cada oración se sintetiza por separado, se mide su
duración real y se concatenan con pausas; el video usa esos límites exactos.

Proveedor: edge-tts (voz neuronal, gratis) → gTTS (respaldo, avisa por warning).
Sin TTS (`EDGETAPE_TTS_PROVIDER=none` o sin dependencias) devuelve audio=None y
el video sigue sin voz.
"""

import logging
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .media import FFMPEG

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 48000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_DEFAULT_PAUSE_MS = 220
_COMMA_PAUSE_MS = 140
# Tras 3 fallos seguidos de TTS se deja de intentar: un guion de 15 min con
# gTTS sin red no puede esperar 90 timeouts.
_MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class Narration:
    audio: str | None
    starts: list[float] = field(default_factory=list)
    ends: list[float] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    total: float = 0.0
    provider: str = "none"
    voice: str = ""
    warnings: list[str] = field(default_factory=list)


def _provider() -> str:
    raw = os.environ.get("EDGETAPE_TTS_PROVIDER", "auto").strip().lower()
    if raw in {"none", "off", "0", "sin"}:
        return "none"
    if raw in {"edge", "edge-tts"}:
        return "edge"
    if raw in {"gtts", "gtts"}:
        return "gtts"
    return "edge" if _edge_available() else "gtts"


def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _pause_ms(sentence: str) -> int:
    raw = os.environ.get("EDGETAPE_TTS_PAUSE_MS")
    base = _DEFAULT_PAUSE_MS
    if raw:
        try:
            base = max(0, min(1200, int(raw)))
        except ValueError:
            pass
    text = sentence.strip()
    if text.endswith((",", ";", ":")):
        return max(0, min(base, _COMMA_PAUSE_MS))
    if text.endswith((".", "?", "!", "…")):
        return base
    return int(base * 0.75)


def _estimate_seconds(text: str) -> float:
    words = max(1, len(str(text).split()))
    return max(0.8, words / 2.6)


def _to_wav(src: Path, out: Path) -> bool:
    try:
        result = subprocess.run(
            [
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src), "-ar", str(_SAMPLE_RATE), "-ac", str(_CHANNELS),
                "-c:a", "pcm_s16le", "-f", "wav", str(out),
            ],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0 and out.exists() and out.stat().st_size > 44
    except Exception as exc:  # noqa: BLE001
        logger.warning("no se pudo convertir TTS a wav (%s)", exc)
        return False


def _wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or _SAMPLE_RATE)
    except Exception:  # noqa: BLE001
        return 0.0


def _silence_wav(path: Path, seconds: float) -> None:
    frames = max(0, int(round(seconds * _SAMPLE_RATE)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(b"\x00" * (frames * _CHANNELS * _SAMPLE_WIDTH))


def _concat_wavs(parts: list[Path], out: Path) -> bool:
    """Concatena WAV PCM uniformes (48k/mono/s16) sin depender de ffmpeg concat."""
    try:
        with wave.open(str(out), "wb") as dst:
            dst.setnchannels(_CHANNELS)
            dst.setsampwidth(_SAMPLE_WIDTH)
            dst.setframerate(_SAMPLE_RATE)
            for part in parts:
                with wave.open(str(part), "rb") as src:
                    dst.writeframes(src.readframes(src.getnframes()))
        return out.exists() and out.stat().st_size > 44
    except Exception as exc:  # noqa: BLE001
        logger.warning("no se pudo concatenar la narración (%s)", exc)
        return False


def _postprocess(src: Path, out: Path) -> Path | None:
    """Nivel de voz consistente y sin ruido de baja frecuencia."""
    try:
        result = subprocess.run(
            [
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src),
                "-af",
                "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11,"
                "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
                "-ar", str(_SAMPLE_RATE), "-ac", "2",
                "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(out),
            ],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-proceso de voz falló (%s)", exc)
    return None


def build_narration(
    sentences: list[str],
    voice: str,
    tmp: Path,
    pause_ms: int | None = None,
) -> Narration:
    """Sintetiza cada oración y devuelve límites reales para el montaje.

    `starts/ends` incluyen la pausa posterior a cada oración, así el corte de la
    escena coincide con el inicio de la siguiente. `durations` es el audio puro
    de cada oración (sin pausa).
    """
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    sentences = [str(s).strip() for s in sentences if str(s).strip()]
    if not sentences:
        return Narration(None, warnings=["guion vacío: no hay narración"])

    provider = _provider()
    if provider == "none":
        return Narration(None, provider="none", voice=voice,
                         warnings=["TTS desactivado (EDGETAPE_TTS_PROVIDER=none)"])

    # Import perezoso para que monkeypatches de tests sobre ai_generate.build_voiceover
    # sigan aplicando y para evitar un ciclo de imports al cargar el módulo.
    from . import ai_generate as _aig

    parts: list[Path] = []
    durations: list[float] = []
    starts: list[float] = []
    ends: list[float] = []
    total = 0.0
    warnings: list[str] = []
    actual_providers: set[str] = set()
    failures = 0
    synth_ok = 0

    for i, sentence in enumerate(sentences):
        pause = (pause_ms if pause_ms is not None else _pause_ms(sentence)) / 1000.0
        starts.append(total)
        wav: Path | None = None
        if failures < _MAX_CONSECUTIVE_FAILURES:
            mp3 = tmp / f"tts_{i}.mp3"
            try:
                _aig._LAST_TTS_PROVIDER = None
                produced = _aig.build_voiceover(sentence, voice, mp3)
                used = getattr(_aig, "_LAST_TTS_PROVIDER", None)
                if used:
                    actual_providers.add(used)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS de la oración %d falló (%s)", i, exc)
                produced = None
            if produced:
                wav = tmp / f"tts_{i}.wav"
                if not _to_wav(Path(produced), wav):
                    wav = None
            if wav is None:
                failures += 1
                if failures >= _MAX_CONSECUTIVE_FAILURES:
                    warnings.append(
                        "el TTS falló repetidamente: el resto de la narración "
                        "queda en silencio"
                    )
            else:
                failures = 0
                synth_ok += 1
        if wav is None:
            seconds = _estimate_seconds(sentence)
            wav = tmp / f"silence_{i}.wav"
            _silence_wav(wav, seconds)
        dur = _wav_seconds(wav)
        if dur <= 0.05:
            dur = _estimate_seconds(sentence)
            _silence_wav(wav, dur)
        parts.append(wav)
        durations.append(dur)
        total += dur
        if pause > 0:
            silence = tmp / f"pause_{i}.wav"
            _silence_wav(silence, pause)
            parts.append(silence)
            total += pause
        ends.append(total)

    if synth_ok == 0:
        return Narration(
            None, provider=provider, voice=voice,
            warnings=warnings + ["no se pudo sintetizar ninguna oración: video sin voz"],
        )

    raw = tmp / "voice_raw.wav"
    if not _concat_wavs(parts, raw):
        return Narration(None, provider=provider, voice=voice,
                         warnings=warnings + ["no se pudo concatenar la narración"])

    out = tmp / "voice.m4a"
    processed = _postprocess(raw, out)
    audio = str(processed or raw)
    used_provider = provider
    if actual_providers:
        used_provider = "edge" if actual_providers == {"edge"} else "gtts"
    if "gtts" in actual_providers:
        if provider == "gtts":
            warnings.append(
                "voz gTTS configurada (calidad robótica): usá edge-tts para "
                "una voz neuronal"
            )
        else:
            warnings.append(
                "voz gTTS (robótica): edge-tts falló; instalá/revisá edge-tts "
                "o configurá un TTS neuronal para mejorar la locución"
            )
    elif provider != "none" and not _edge_available():
        used_provider = "gtts"
        warnings.append(
            "voz gTTS (calidad inferior): instalá edge-tts o configurá un TTS "
            "neuronal para mejorar la locución"
        )
    logger.info(
        "narración: %d oraciones, %.1fs reales, proveedor %s",
        len(sentences), total, used_provider,
    )
    return Narration(
        audio=audio,
        starts=starts,
        ends=ends,
        durations=durations,
        total=total,
        provider=used_provider,
        voice=voice,
        warnings=warnings,
    )
