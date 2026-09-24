from __future__ import annotations

import json
import random
import re
import subprocess
from pathlib import Path

FFPROBE = "ffprobe"
FFMPEG = "ffmpeg"

_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "]+"
)

_VIRAL_LABELS = [
    "MOMENTO CLAVE",
    "NO TE LO PIERDAS",
    "ESTO CAMBIA TODO",
    "LO QUE NADIE TE CUENTA",
    "ATENCIÓN ⚡",
]

_FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ARIALBD.TTF",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    # Linux (Debian/Ubuntu/Fedora)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/SFNSText.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _find_font() -> str:
    import os
    custom = os.environ.get("EDGETAPE_FONT")
    candidates = ([custom] if custom else []) + _FONT_CANDIDATES
    for c in candidates:
        if c and Path(c).exists():
            return c
    return ""


def _fontfile_arg() -> str:
    font = _find_font()
    return f"fontfile={font}:" if font else ""


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


def extract_best_thumbnail(
    src: str | Path, start: float, end: float, out: str | Path, width: int = 360
) -> None:
    """Extract the frame with highest brightness variance from the clip."""
    dur = end - start
    if dur <= 0:
        extract_thumbnail(src, start, out, width)
        return
    candidates = [start + dur * f for f in (0.15, 0.3, 0.5, 0.7)]
    best_at = candidates[0]
    best_var = -1.0
    for t in candidates:
        try:
            cmd = [
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, t):.3f}",
                "-i", str(src),
                "-frames:v", "1",
                "-vf", f"signalstats,metadata=print:file=-",
                "-f", "null", "-",
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            var = 0.0
            for line in r.stderr.split("\n"):
                if "YAVG" in line:
                    try:
                        var += abs(float(line.split("=")[-1]))
                    except ValueError:
                        pass
            if var > best_var:
                best_var = var
                best_at = t
        except Exception:
            pass
    extract_thumbnail(src, best_at, out, width)


def _emoji_strip(text: str) -> str:
    return _EMOJI_RE.sub(" ", text)


def extract_thumbnail_with_overlay(
    src: str | Path,
    at: float,
    out: str | Path,
    text: str,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """Extract thumbnail 9:16 with viral-style text overlay.

    Texto en blanco con caja azul `#1E3A8A` y trazo amarillo `#FFC647`,
    banda superior dorada con etiqueta viral + banda inferior con gancho.
    Usa el gancho del clip en MAYÚSCULAS (máx ~24 caracteres, sin emojis
    que ffmpeg drawtext no renderiza).
    """
    clean = _emoji_strip(str(text))
    snippet = " ".join(clean.upper().split())[:24]
    if len(snippet) < 8:
        snippet = "MOMENTO CLAVE"
    label = random.choice(_VIRAL_LABELS)
    safe_quote = snippet.replace("'", r"\'").replace(":", r"\:").replace("%", r"\%")
    safe_label = label.replace("'", r"\'").replace(":", r"\:").replace("%", r"\%")
    ff = _fontfile_arg()
    fontsize = max(44, min(84, int(width / len(snippet) * 0.62)))
    label_size = int(fontsize * 0.5)
    label_y = int(height * 0.18) - label_size // 2
    box_top = int(height * 0.60)
    box_h = int(height * 0.14)
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at):.3f}",
        "-i", str(src),
        "-frames:v", "1",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"drawbox=x=0:y=0:w={width}:h={int(height*0.10)}:color=#FFC647:t=fill,"
        f"drawtext=text='{safe_label}':{ff}"
        f"fontsize={label_size}:fontcolor=#1E3A8A:"
        f"fontweight=bold:"
        f"x=(w-text_w)/2:y={label_y}:"
        f"drawbox=x=0:y={box_top}:w={width}:h={box_h}:"
        f"color=#1E3A8A@0.75:t=fill,"
        f"drawtext=text='{safe_quote}':{ff}"
        f"fontsize={fontsize}:fontcolor=white:"
        f"borderw=3:bordercolor=#FFC647:"
        f"x=(w-text_w)/2:y={int(height*0.60) + (box_h - fontsize) // 2}:"
        f"line_spacing=6",
        "-q:v", "2",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not Path(out).exists():
        fallback_cmd = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, at):.3f}",
            "-i", str(src),
            "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-q:v", "2",
            str(out),
        ]
        subprocess.run(fallback_cmd, capture_output=True, text=True)


def extract_multiple_thumbnails(
    src: str | Path, start: float, end: float, out_dir: str | Path,
    clip_id: str, count: int = 5, width: int = 360,
) -> list[str]:
    """Extract `count` thumbnail frames evenly spaced across the clip.
    Returns list of filenames (e.g. ["c1_thumb_0.jpg", ...])."""
    from pathlib import Path as P

    out_dir = P(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dur = end - start
    if dur <= 0:
        fname = f"{clip_id}_thumb_0.jpg"
        extract_thumbnail(src, start, out_dir / fname, width)
        return [fname]

    fractions = [0.1, 0.25, 0.5, 0.75, 0.9][:count]
    filenames = []
    for i, frac in enumerate(fractions):
        t = start + dur * frac
        fname = f"{clip_id}_thumb_{i}.jpg"
        try:
            extract_thumbnail(src, t, out_dir / fname, width)
            filenames.append(fname)
        except Exception:
            pass
    return filenames