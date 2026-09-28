from __future__ import annotations

import json
import random
import re
import subprocess
import textwrap
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
    "ATENCIÓN",
    "MIRA ESTO AHORA",
    "NO PUEDES IGNORARLO",
    "PARA DE HACER SCROLL",
    "EL SECRETO ESTA AQUI",
    "TE VA A SORPRENDER",
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
    if not font:
        return ""
    # La ruta va dentro del filtro drawtext: el `:` separa opciones y `\` es
    # carácter de escape, así que ambos deben escaparse (clave en Windows).
    escaped = font.replace(":", "\\:").replace("\\", "\\\\")
    return f"fontfile={escaped}:"


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
    caption: str | None = None,
) -> None:
    """Corta un clip. `mode` controla el formato de salida:
    - "vertical_blur": 1080x1920 (9:16) con fondo borroso, contenido completo.
    - "vertical_crop": 1080x1920 recortado al centro.
    - "original": mantiene las dimensiones de la fuente.

    Si `caption` se pasa y `EDGETAPE_BURN_SUBTITLES=1` está activo, se quema la
    línea del clip como subtítulo estilo viral (blanco con borde azul EDGE y
    trazo amarillo MARK), reutilizando la fuente cross-platform de miniaturas.
    """
    import os
    burn = os.environ.get("EDGETAPE_BURN_SUBTITLES") == "1"
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
        vf = (
            "split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:2[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    elif mode == "vertical_crop":
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    else:
        vf = ""
    if burn and caption:
        over = _caption_filter(_emoji_strip(str(caption)))
        if vf:
            vf = f"{vf},{over}"
        else:
            vf = f"format=yuv420p,{over}"
    if vf:
        cmd += ["-vf", vf]
    cmd += [str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr.strip()}")


def _caption_filter(text: str, width: int = 1080, height: int = 1920) -> str:
    """drawtext estilo viral: blanco, borde azul EDGE y trazo amarillo MARK.

    Envuelve el texto en líneas de ~22 caracteres y escapa metacharacteres
    de drawtext y secuencias que ffmpeg no renderiza (emojis incluidos).
    """
    wrapped = textwrap.fill(" ".join(text.split()), width=22)
    lines = wrapped.splitlines()[:4]
    safe = []
    for line in lines:
        e = (
            line.replace("\\", r"\\")
            .replace("'", r"\'")
            .replace(":", r"\:")
            .replace("%", r"\%")
            .replace(",", r"\,")
            .replace("[", r"\[")
            .replace("]", r"\]")
        )
        safe.append(e)
    payload = "\\n".join(safe)
    if not payload:
        return ""
    ff = _fontfile_arg()
    fontsize = 64 if len(safe) <= 2 else 52
    box_y = int(height * 0.82)
    return (
        f"drawtext=text='{payload}':{ff}"
        f"fontsize={fontsize}:fontcolor=white:"
        f"borderw=4:bordercolor=#1E3A8A:"
        f"shadowcolor=#FFC647:shadowx=2:shadowy=2:"
        f"x=(w-text_w)/2:y={box_y}:line_spacing=14"
    )


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
    label: str | None = None,
    variant: int = 0,
) -> None:
    """Extract thumbnail 9:16 (or custom aspect) with viral-style text overlay.

    Texto en blanco con caja azul `#1E3A8A` y trazo amarillo `#FFC647`,
    banda superior dorada con etiqueta viral + banda inferior con gancho.
    Usa el gancho del clip en MAYÚSCULAS (sin emojis que ffmpeg no renderiza).
    El texto se envuelve en hasta 2 líneas ajustadas al ancho objetivo.
    `label` fuerza una etiqueta; `variant` rota etiqueta + posición para que
    las opciones de un mismo clip se vean distintas.
    """
    clean = _emoji_strip(str(text))
    snippet = " ".join(clean.upper().split())
    if len(snippet) < 8:
        snippet = "MOMENTO CLAVE"
    if label is None:
        label = _VIRAL_LABELS[variant % len(_VIRAL_LABELS)]

    max_chars = max(10, int(width * 0.093))
    lines = textwrap.wrap(snippet, width=max_chars)[:2]
    if not lines:
        lines = ["MOMENTO CLAVE"]
    n_lines = len(lines)

    fontsize = _fit_fontsize(lines, width)
    safe_lines = []
    for line in lines:
        e = (
            line.replace("\\", r"\\")
            .replace("'", r"\'")
            .replace(":", r"\:")
            .replace("%", r"\%")
            .replace(",", r"\,")
            .replace("[", r"\[")
            .replace("]", r"\]")
        )
        safe_lines.append(e)
    payload = "\\n".join(safe_lines)
    safe_label = label.replace("'", r"\'").replace(":", r"\:").replace("%", r"\%")
    ff = _fontfile_arg()
    label_size = max(18, int(width * 0.032))
    label_y = int(height * 0.18) - label_size // 2
    box_top = int(height * 0.58)
    box_h = int(height * (0.19 if n_lines == 2 else 0.14))
    box_y = box_top + (box_h - n_lines * fontsize - (n_lines - 1) * 10) // 2
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
        f"x=(w-text_w)/2:y={label_y},"
        f"drawbox=x=0:y={box_top}:w={width}:h={box_h}:"
        f"color=#1E3A8A@0.75:t=fill,"
        f"drawtext=text='{payload}':{ff}"
        f"fontsize={fontsize}:fontcolor=white:"
        f"borderw=3:bordercolor=#FFC647:"
        f"x=(w-text_w)/2:y={box_y}:"
        f"line_spacing=10",
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


def _fit_fontsize(lines: list[str], width: int) -> int:
    """Elige un fontsize para que la línea más larga quepa en el ancho."""
    longest = max((len(l) for l in lines if l), default=12)
    # ~0.62 ancho por carácter a fontsize dado; deja margen de borde.
    natural = int(width * 0.94 / max(1.0, longest * 0.62))
    low, high = int(width * 0.045), int(width * 0.10)
    return max(low, min(high, natural))


# Fallbacks para el texto explosivo de Shorts (máx 3 palabras)
_EXPLOSIVE_FALLBACKS = ["INCREÍBLE", "WOW", "ÉPICO", "NO LO CREERÁS"]


def _explosive_words(text: str, variant: int = 0) -> str:
    """Gancho recortado a MÁXIMO 3 palabras en MAYÚSCULAS (estilo Shorts).

    Limpia signos de puntuación en los bordes y cae a un fallback llamativo
    si el hook no aporta palabras. `variant` elige el fallback de forma
    determinista para que las opciones de un mismo clip se distingan.
    """
    clean = _emoji_strip(str(text)).upper().replace("\n", " ")
    token_re = re.compile(r"[^A-ZÁÉÍÓÚÑÜ0-9'°%$#&!?. ]+")
    tokens = token_re.sub(" ", clean).split()
    words: list[str] = []
    for tok in tokens[:3]:
        w = re.sub(r"^[^A-ZÁÉÍÓÚÑÜ0-9'°%$#&]+", "", tok)
        w = re.sub(r"[^A-ZÁÉÍÓÚÑÜ0-9'°%$#&]+$", "", w)
        if w:
            words.append(w)
    if not words:
        return _EXPLOSIVE_FALLBACKS[variant % len(_EXPLOSIVE_FALLBACKS)]
    return " ".join(words)


def _explosive_lines(text: str, max_chars: int) -> list[str]:
    """Envuelve el texto en hasta 2 líneas por palabras, respetando max_chars."""
    lines: list[str] = []
    cur = ""
    for w in text.split():
        cand = (cur + " " + w).strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:2]


def _pent(cx: float, cy: float, r: float, rot: float, draw, color: tuple) -> None:
    """Dibuja un pentágono relleno (usado para el balón de fútbol)."""
    import math
    pts = [(cx + r * math.cos(rot + k * 2.0944), cy + r * math.sin(rot + k * 2.0944)) for k in range(5)]
    draw.polygon(pts, fill=color)


def _shorts_overlay(
    base: "Image.Image", text: str, variant: int, size: tuple[int, int]
) -> "Image.Image":
    """Overlay estilo explosivo viral para 1080x1920: rayos de luz verde/amarilla,
    partículas, balón de fútbol con estela, rayo ⚡ y texto gigante con trazo negro.
    Todo se dibuja con Pillow (los emojis no se renderizan con drawtext de ffmpeg).
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = size
    rng = random.Random(variant * 97 + len(text))

    GREEN = (0, 255, 136)
    YELLOW = (255, 214, 51)
    WHITE = (255, 255, 255)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # ── Rayos de luz desde las esquinas superiores e inferior derecha ──
    foci = [(0, 0), (W, 0), (W, H)]
    for fx, fy in foci:
        base_angle = 0.0 if fy == 0 else 1.5708
        for i in range(4):
            color = GREEN if i % 2 == 0 else YELLOW
            alpha = rng.randint(38, 70)
            spread = rng.uniform(0.10, 0.24)
            angle = base_angle + rng.uniform(-spread, spread)
            import math
            length = int(max(W, H) * rng.uniform(0.55, 1.05))
            tip = (fx - math.cos(angle) * length, fy - math.sin(angle) * length)
            perp = angle + 1.5708
            half = int(W * rng.uniform(0.012, 0.035))
            p1 = (fx - math.cos(perp) * half, fy - math.sin(perp) * half)
            p2 = (fx + math.cos(perp) * half, fy + math.sin(perp) * half)
            d.polygon([(fx, fy), p1, tip, p2], fill=color + (alpha,))

    # ── Partículas y chispas ──
    for _ in range(70):
        x = rng.randrange(W)
        y = rng.randrange(H)
        r = rng.uniform(1.5, 4.5)
        color = rng.choice([WHITE, YELLOW, GREEN, WHITE])
        alpha = rng.randint(120, 235)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color + (alpha,))
    for _ in range(14):
        cx = rng.randrange(W)
        cy = rng.randrange(H)
        arm = rng.uniform(4, 9)
        d.line([(cx - arm, cy), (cx + arm, cy)], fill=YELLOW + (200,), width=2)
        d.line([(cx, cy - arm), (cx, cy + arm)], fill=YELLOW + (200,), width=2)

    # ── Balón de fútbol con estela de movimiento ──
    bx = int(W * rng.uniform(0.62, 0.80))
    by = int(H * rng.uniform(0.64, 0.74))
    ball_r = int(W * rng.uniform(0.055, 0.075))
    for k in range(6):
        x0 = bx - int(ball_r * (1.4 + k * 1.1))
        x1 = bx + ball_r + int(ball_r * 0.6)
        y1 = by - int(ball_r * (0.5 + k * 0.28))
        y2 = by + int(ball_r * (0.5 + k * 0.28))
        d.line([(x0, y1), (x1, y2)], fill=YELLOW + (120,), width=int(W * 0.004) + 1)
    d.ellipse([bx - ball_r, by - ball_r, bx + ball_r, by + ball_r],
              fill=WHITE, outline=(24, 24, 24), width=max(3, int(W * 0.003)))
    ring = [(0.0, -0.70), (0.67, -0.22), (0.41, 0.55), (-0.41, 0.55), (-0.67, -0.22)]
    _pent(bx, by, ball_r * 0.26, 1.5708, d, (30, 30, 30))
    for i, (ux, uy) in enumerate(ring):
        _pent(bx + ux * ball_r * 0.78, by + uy * ball_r * 0.78,
              ball_r * (0.20 + (i % 2) * 0.05), 1.5708 + i * 1.2566, d, (30, 30, 30))

    # ── Rayo ⚡ (polígono amarillo; Pillow no depende de glifos de emoji) ──
    lx = int(W * 0.17)
    ly = int(H * 0.30)
    s = int(W * 0.052)
    bolt = [
        (lx + s * 0.2, ly + s * 0.0), (lx - s * 0.7, ly + s * 1.6),
        (lx - s * 0.1, ly + s * 1.6), (lx - s * 0.8, ly + s * 3.1),
        (lx + s * 0.9, ly + s * 1.3), (lx + s * 0.1, ly + s * 1.3),
        (lx + s * 0.7, ly + s * 0.0),
    ]
    d.polygon(bolt, fill=YELLOW + (235,), outline=(0, 0, 0, 150))

    # ── Banda inferior oscura (gradiente) para contraste del texto ──
    band_top = int(H * 0.58)
    band_h = H - band_top
    for i in range(0, band_h, 4):
        alpha = int(155 * (i / band_h))
        d.rectangle([0, band_top + i, W, band_top + i + 4], fill=(0, 0, 0, alpha))

    # ── Texto gigante: máx 2 líneas, trazo negro, relleno blanco ──
    max_chars = max(6, int(W * 0.021))
    lines = _explosive_lines(text, max_chars)
    if not lines:
        lines = [text]
    font = _find_font()
    size_cap = int(W * 0.15)
    low = int(W * 0.05)
    fontsize = size_cap
    try:
        while fontsize > low:
            fnt = ImageFont.truetype(font, fontsize)
            widest = max((d.textlength(l, font=fnt) for l in lines), default=0.0)
            if widest <= W * 0.92:
                break
            fontsize -= 6
    except Exception:  # noqa: BLE001
        fontsize = low
    try:
        fnt = ImageFont.truetype(font, fontsize)
    except Exception:  # noqa: BLE001
        try:
            fnt = ImageFont.load_default(size=fontsize)
        except TypeError:
            fnt = ImageFont.load_default()
            fontsize = 40
    line_h = int(fontsize * 1.18)
    y = int(H * 0.70)
    stroke = max(3, int(fontsize * 0.09))
    for line in lines:
        # resaltado marcador (línea amarilla detrás del texto)
        w = d.textlength(line, font=fnt)
        d.rectangle([(W - w) / 2 - int(W * 0.012), y + int(fontsize * 1.02),
                     (W + w) / 2 + int(W * 0.012), y + int(fontsize * 1.10)],
                    fill=(0, 0, 0, 90))
        d.rectangle([(W - w) / 2 - int(W * 0.012), y + int(fontsize * 1.10),
                     (W + w) / 2 + int(W * 0.012), y + int(fontsize * 1.16)],
                    fill=YELLOW + (220,))
        d.text(((W - w) / 2, y), line, font=fnt, fill=WHITE,
               stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    return overlay


def extract_viral_shorts_thumbnail(
    src: str | Path,
    at: float,
    out: str | Path,
    text: str,
    variant: int = 0,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """Miniatura explosiva 1080x1920 (Shorts): frame saturado + overlay viral.

    ffmpeg extrae el frame recortado 9:16 con `eq=saturation=1.7` y Pillow
    compone rayos de luz, partículas, balón, rayo ⚡ y el gancho en MAYÚSCULAS
    (máx 3 palabras) con trazo negro. `variant` rota la semilla para que las
    opciones de un mismo clip se distingan. Si Pillow no está disponible, cae
    al overlay dorado clásico.
    """
    import os
    import tempfile

    W, H = int(width), int(height)
    words = _explosive_words(text, variant)
    try:
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="edgetape_shorts_") as tmp:
            base_tmp = os.path.join(tmp, "base.jpg")
            cmd = [
                FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, at):.3f}",
                "-i", str(src),
                "-frames:v", "1",
                "-vf",
                f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},eq=saturation=1.7:contrast=1.05",
                "-q:v", "2",
                base_tmp,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 or not Path(base_tmp).exists():
                raise RuntimeError(f"ffmpeg frame failed: {result.stderr.strip()}")
            base = Image.open(base_tmp).convert("RGB").resize((W, H), Image.LANCZOS)
            overlay = _shorts_overlay(base, words, variant, (W, H))
            out_img = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
            out_img.save(out, "JPEG", quality=88)
    except Exception:  # noqa: BLE001 — fallback al overlay dorado clásico
        extract_thumbnail_with_overlay(
            src, at, out, text, width=W, height=H, variant=variant
        )


def extract_multiple_thumbnails(
    src: str | Path, start: float, end: float, out_dir: str | Path,
    clip_id: str, count: int = 5, width: int = 360,
    text: str = "", variant: int = 0,
) -> list[str]:
    """Extract `count` thumbnail frames evenly spaced across the clip.

    Si `text` no está vacío, cada frame se renderiza con overlay viral
    (gancho + etiqueta llamativa), rotando la etiqueta/estilo con `variant`
    para que las opciones de un mismo clip se distingan entre sí. El resto
    de fracciones conserva su variante de etiqueta secuencialmente.
    Returns list of filenames (e.g. ["c1_thumb_0.jpg", ...]).
    """
    from pathlib import Path as P

    out_dir = P(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dur = end - start
    if dur <= 0:
        fname = f"{clip_id}_thumb_0.jpg"
        if text:
            # thumb único: estilo explosivo Shorts (1080x1920)
            extract_viral_shorts_thumbnail(src, start, out_dir / fname, text, variant=variant)
        else:
            extract_thumbnail(src, start, out_dir / fname, width)
        return [fname]

    fractions = [0.1, 0.25, 0.5, 0.75, 0.9][:count]
    filenames = []
    for i, frac in enumerate(fractions):
        t = start + dur * frac
        fname = f"{clip_id}_thumb_{i}.jpg"
        try:
            if text:
                if i < count - 1:
                    # opciones por defecto: estilo explosivo Shorts a resolución completa
                    extract_viral_shorts_thumbnail(
                        src, t, out_dir / fname, text, variant=variant + i,
                    )
                else:
                    # última opción: miniatura viral dorada clásica
                    extract_thumbnail_with_overlay(
                        src, t, out_dir / fname, text, width=width,
                        height=_aspect_height(width), variant=variant + i,
                    )
            else:
                extract_thumbnail(src, t, out_dir / fname, width)
            filenames.append(fname)
        except Exception:
            pass
    return filenames


def _aspect_height(width: int, ratio: float = 16 / 9) -> int:
    return int(width * ratio)