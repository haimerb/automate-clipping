from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .media import FFMPEG, _emoji_strip, _find_font, _fontfile_arg

# YouTube channel branding request params:
#   banner 2560x1440 (zona segura central ~1546x423), max 6 MB
#   avatar 800x800 circular, min 98x98
BANNER_SIZE = (2560, 1440)
AVATAR_SIZE = (800, 800)

_BANNER_BG_EMBED = "https://images.unsplash.com/photo-1517466787929-bc90951d0974"  # cancha
_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _fit_banner_fontsize(text: str, width: int) -> int:
    """Tamaño de fuente para que el texto quepa en el banner con margen."""
    longest = max((len(t) for t in text.split("\n") if t), default=12)
    return int(min(width * 0.30, width * 0.92 / max(1.0, longest * 0.62)))


def _esc_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


# ──────────────────────────────────────────────────────────────────────────
# Banner 2560x1440 (ffmpeg + drawtext)
# ──────────────────────────────────────────────────────────────────────────

def make_gradient_background(out: Path, size: tuple[int, int]) -> Path:
    """Fondo gradiente (azul EDGE → oscuro) generado por ffmpeg como respaldo
    cuando no hay imagen remota disponible."""
    w, h = size
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=#1E3A8A:s={w}x{h}:d=1",
        "-vf", (
            f"drawbox=x=0:y=0:w={w}:h={h}:color=#1E3A8A:t=fill,"
            f"drawbox=x=0:y=0:w={w}:h={h//2}:color=#3B6AD1:t=fill,"
            f"drawbox=x=0:y={h//3}:w={w}:h={h}:color=#0F172A@0.55:t=fill"
        ),
        "-frames:v", "1", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"no se pudo crear fondo de banner: {result.stderr.strip()}")
    return out


def _detect_image_ext(data: bytes) -> str:
    """Detecta el formato real por magic bytes para que ffmpeg no asuma por extensión."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:12] == b"GIF87a" or data[:12] == b"GIF89a":
        return ".gif"
    if data.startswith(b"MM\x00\x2a") or data.startswith(b"II\x2a\x00"):
        return ".tiff"
    raise RuntimeError("el contenido descargado no parece una imagen")


def _fetch_banner_background(bg: str | None, dest: Path) -> Path:
    """Descarga la imagen de fondo (http/https) o copia un path local.
    Lanza RuntimeError si no es alcanzable o no es imagen."""
    bg = (bg or _BANNER_BG_EMBED).strip()
    if not bg.lower().startswith(("http://", "https://")):
        raise RuntimeError("la URL de fondo debe ser http(s)")
    import httpx
    resp = httpx.get(
        bg,
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": _AGENT},
    )
    resp.raise_for_status()
    if not resp.content:
        raise RuntimeError("imagen de fondo vacía")
    # No usar la extensión del nombre: ffmpeg decodifica según magic bytes.
    final = dest.with_suffix(_detect_image_ext(resp.content))
    final.write_bytes(resp.content)
    return final


def generate_banner(
    out: Path,
    channel_name: str = "FUTBOL VIRAL EDITS",
    tagline: str = "Resúmenes virales de fútbol",
    background_url: str | None = None,
) -> Path:
    """Genera el banner 2560x1440. Si `background_url` falla, usa gradiente."""
    w, h = BANNER_SIZE
    title = _emoji_strip(str(channel_name)).upper() or "FUTBOL VIRAL EDITS"
    tag = _emoji_strip(str(tagline))[:48]
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="edgetape-banner-") as tmp:
        bg_path = Path(tmp) / "bg"
        try:
            bg_path = _fetch_banner_background(background_url, Path(tmp) / "bg")
        except Exception:  # noqa: BLE001
            bg_path = make_gradient_background(Path(tmp) / "bg.jpg", BANNER_SIZE)

        ff = _fontfile_arg()
        title_size = _fit_banner_fontsize(title, w)
        safe_title = _esc_drawtext(title)
        safe_tag = _esc_drawtext(tag)
        # banda oscura central para legibilidad + franja amarilla de marca
        band_top = int(h * 0.40)
        band_h = int(h * 0.22)
        title_y = band_top + int(band_h * 0.10)
        tag_y = title_y + int(title_size * 1.08)
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"eq=brightness=-0.12:saturation=1.12,"
            f"drawbox=x=0:y={band_top}:w={w}:h={band_h}:color=#0F172A@0.62:t=fill,"
            f"drawbox=x=0:y={band_top}:w={w}:h=12:color=#FFC647:t=fill,"
            f"drawtext=text='{safe_title}':{ff}"
            f"fontsize={title_size}:fontcolor=#FFC647:"
            f"borderw=0:shadowcolor=#1E3A8A:shadowx=4:shadowy=4:"
            f"x=(w-text_w)/2:y={title_y},"
            f"drawtext=text='{safe_tag}':{ff}"
            f"fontsize={int(title_size / 3.1)}:fontcolor=white:"
            f"x=(w-text_w)/2:y={tag_y}"
        )
        cmd = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(bg_path),
            "-vf", vf,
            "-frames:v", "1",
            "-q:v", "2",
            str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(f"no se pudo generar el banner: {result.stderr.strip()}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Avatar 800x800 (PIL: escudo + balón + iniciales)
# ──────────────────────────────────────────────────────────────────────────

def _pentagon(cx: float, cy: float, r: float, rotation_deg: float = 0.0) -> list[tuple[float, float]]:
    import math
    pts = []
    for i in range(5):
        ang = math.radians(rotation_deg + i * 72 - 90)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _draw_soccer_ball(draw, cx: float, cy: float, r: float, fill="#ffffff", outline="#14161A") -> None:
    """Balón estilizado: círculo blanco con pentágonos negros."""
    from PIL import Image, ImageDraw  # noqa: F401

    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=max(2, int(r * 0.08)))
    draw.polygon(_pentagon(cx, cy, r * 0.36, -90), fill=outline)
    for k in range(5):
        ang = k * 72 - 90
        import math
        p_cx = cx + r * 0.62 * math.cos(math.radians(ang))
        p_cy = cy + r * 0.62 * math.sin(math.radians(ang))
        draw.polygon(_pentagon(p_cx, p_cy, r * 0.20, ang), fill=outline)


def _draw_shield(draw, cx: float, cy: float, width: float, height: float, fill="#1E3A8A", outline="#FFC647") -> None:
    """Escudo con base redondeada y punta inferior."""
    half = width / 2
    top = cy - height / 2
    bottom = cy + height / 2
    pts = [
        (cx - half, top),
        (cx + half, top),
        (cx + half, top + height * 0.22),
        (cx + half * 0.92, top + height * 0.55),
        (cx + half * 0.55, bottom),
        (cx - half * 0.55, bottom),
        (cx - half * 0.92, top + height * 0.55),
        (cx - half, top + height * 0.22),
    ]
    draw.polygon(pts, fill=fill, outline=outline, width=max(4, int(width * 0.035)))


def generate_avatar(
    out: Path,
    channel_name: str = "FUTBOL VIRAL EDITS",
) -> Path:
    """Genera el avatar 800x800: escudo azul con FVE, balón y marca."""
    from PIL import Image, ImageDraw, ImageFont

    size = AVATAR_SIZE[0]
    img = Image.new("RGB", AVATAR_SIZE, "#152C6B")
    draw = ImageDraw.Draw(img)

    # degradado vertical EDGE → dark
    import math
    top_color = (30, 58, 138)
    bottom_color = (15, 23, 42)
    for y in range(size):
        t = y / size
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line((0, y, size, y), fill=(r, g, b))

    cx, cy = size / 2, size / 2
    # anillo exterior (marca amarilla)
    ring_r = int(size * 0.46)
    draw.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline="#FFC647", width=10,
    )
    # escudo centrado
    _draw_shield(draw, cx, cy + size * 0.02, size * 0.62, size * 0.62)
    # iniciales
    initials = "FVE"
    if channel_name.strip():
        words = [w for w in _emoji_strip(channel_name).upper().split() if len(w) >= 3]
        if words:
            initials = "".join(w[0] for w in words[:3])
    try:
        font = ImageFont.truetype(_find_font() or r"C:\Windows\Fonts\arialbd.ttf", int(size * 0.17))
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (cx - tw / 2 - bbox[0], cy - size * 0.10 - th / 2 - bbox[1]),
        initials, font=font, fill="#FFFFFF",
    )
    # balón debajo de las iniciales
    _draw_soccer_ball(draw, cx, cy + size * 0.24, size * 0.13)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")
    return out


def generate_channel_assets(
    out_dir: Path,
    channel_name: str = "FUTBOL VIRAL EDITS",
    tagline: str = "Resúmenes virales de fútbol",
    background_url: str | None = None,
) -> dict:
    """Genera banner.jpg y avatar.png en `out_dir`. Devuelve metadatos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    banner = generate_banner(
        out_dir / "banner.jpg", channel_name, tagline, background_url
    )
    avatar = generate_avatar(out_dir / "avatar.png", channel_name)

    from datetime import datetime, timezone
    return {
        "channel_name": _emoji_strip(channel_name).upper().strip() or "FUTBOL VIRAL EDITS",
        "tagline": _emoji_strip(tagline)[:80],
        "background_url": background_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "banner_exists": banner.exists(),
        "avatar_exists": avatar.exists(),
    }