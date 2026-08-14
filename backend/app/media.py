from __future__ import annotations

import json
import subprocess
from pathlib import Path

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"


def probe_duration(path: str | Path) -> float:
    cmd = [
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    try:
        return float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("ffprobe returned no duration")


def cut_clip(
    src: str | Path,
    start: float,
    end: float,
    out: str | Path,
    mode: str = "vertical_blur",
) -> None:
    """Corta un clip. `mode` controla el formato de salida:
    - "vertical_blur": 1080x1920 (9:16) con fondo borroso, contenido completo.
    - "vertical_crop": 1080x1920 recortado al centro.
    - "original": mantiene las dimensiones de la fuente.
    """
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{max(0.1, end - start):.3f}",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac",
        "-movflags", "+faststart",
    ]
    if mode == "vertical_blur":
        cmd += [
            "-vf",
            "split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:2[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1",
        ]
    elif mode == "vertical_crop":
        cmd += [
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        ]
    cmd += [str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr.strip()}")


def extract_thumbnail(src: str | Path, at: float, out: str | Path, width: int = 360) -> None:
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at):.3f}",
        "-i", str(src),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "3",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not Path(out).exists():
        raise RuntimeError(f"ffmpeg thumbnail failed: {result.stderr.strip()}")


def has_ffmpeg() -> bool:
    return _which(FFMPEG) is not None


def _which(binary: str) -> str | None:
    import shutil

    return shutil.which(binary)
