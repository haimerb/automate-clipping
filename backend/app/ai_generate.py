from __future__ import annotations

"""Generación procedimental de video con IA como origen: el LLM escribe el guion,
el TTS (edge-tts → gTTS) lo narra y ffmpeg monta un video vertical (Shorts/Reels/TikTok)
u horizontal (YouTube) con gradiente animado + gancho + subtítulos sincronizados.

Degradación total: si el LLM falla se usa el prompt como guion, si el TTS falla el
video sale sin voz y si el render falla el pipeline cae al mock de ffmpeg.
"""

import asyncio
import json
import logging
import math
import os
import random
import re
import subprocess
import time
from pathlib import Path

import httpx

from .media import FFMPEG, FFPROBE, _emoji_strip, _find_font, probe_duration

logger = logging.getLogger(__name__)

# Duraciones aceptadas por /api/generate (los límites reales de publicación los pone
# scorer.FORMAT_LIMITS: shorts/tiktok ≤60, reels ≤90, youtube ≤180).
GENERATE_DURATIONS = [15, 30, 60, 90, 120, 180]

DEFAULT_VOICE = "es-MX-DaliaNeural"

# ~2.6 palabras/segundo en español hablado medio
WORD_RATE = 2.6

_EDGE = "#1E3A8A"
_MARK = "#FFC647"

# Estilos → paleta (fondo superior, fondo inferior, acento amarillo marcador)
_STYLE_PALETTES: dict[str, tuple[str, str, str]] = {
    "professional": (_EDGE, "#0B1026", _MARK),
    "cinematic": ("#0F1B3D", "#04060F", "#E8B33D"),
    "casual": ("#2E4B7C", "#131F38", "#FFB020"),
    "energetic": (_EDGE, "#5A1E38", _MARK),
}

_SCRIPT_SYSTEM = (
    "Eres un guionista experto en videos virales para YouTube (long y Shorts), "
    "TikTok, Facebook e Instagram Reels. Escribes guiones narrados en español "
    "directos al grano, con un gancho fuerte al inicio y frases cortas pensadas "
    "para locución. NUNCA uses inglés ni emojis en el guion. "
    "REGLA CRÍTICA: el guion debe caber en la duración pedida "
    "(≈2.6 palabras por segundo). "
    "Respondes SOLO con JSON válido, sin texto adicional."
)

_VOICE_MAP = {
    "es_mx_female": "es-MX-DaliaNeural",
    "es_mx_male": "es-MX-JorgeNeural",
    "es_es_female": "es-ES-ElviraNeural",
    "es_es_male": "es-ES-AlvaroNeural",
}


def _resolve_voice(voice: str | None) -> str:
    if voice and voice in _VOICE_MAP:
        return _VOICE_MAP[voice]
    if voice and "-" in voice:
        return voice
    return DEFAULT_VOICE


# ── LLM (guion) ─────────────────────────────────────────────


def _complete(system: str, user: str, timeout: float = 60.0) -> str | None:
    """Chat OpenAI-compatible reutilizando la config del repo.

    Prioridad al endpoint remoto documentado en AGENTS.md (hoy `gpt-oss-20b` vía
    `EDGETAPE_LLM_BASE_URL` apuntando a Groq) y después a la clave Groq directa.
    Sin credenciales devuelve None (el script cae al fallback heurístico).
    Retry exponencial ante 429 (límites free: 30 RPM / 6K TPM).
    """
    groq_key = os.environ.get("EDGETAPE_GROQ_API_KEY")
    llm_base = os.environ.get("EDGETAPE_LLM_BASE_URL")
    llm_model = os.environ.get("EDGETAPE_LLM_MODEL")
    llm_key = os.environ.get("EDGETAPE_LLM_API_KEY")
    if llm_base and llm_model:
        url = f"{llm_base.rstrip('/')}/chat/completions"
        model = llm_model
        headers = {"Content-Type": "application/json"}
        if llm_key:
            headers["Authorization"] = f"Bearer {llm_key}"
    elif groq_key:
        url = "https://api.groq.com/openai/v1/chat/completions"
        model = os.environ.get("EDGETAPE_GROQ_MODEL") or "gemma2-9b-it"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {groq_key}",
        }
    else:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
    }
    with httpx.Client(timeout=timeout) as client:
        for attempt in range(5):
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 429:
                wait = (3 * (2 ** attempt)) + random.random() * 2
                logger.warning("LLM 429 en guion — retry %d en %.1fs", attempt + 1, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    return None


_SCRIPT_PROMPT = (
    "Plataforma objetivo: {platform}\n"
    "Duración del video: {duration:.0f} segundos\n"
    "Estilo: {style}\n\n"
    "Tema: {prompt}\n\n"
    "Instrucciones:\n"
    "1. Guion narrado en español de ≈{words} palabras, dividido en {mins[min]} y "
    "máximo {mins[max]} oraciones cortas para locución.\n"
    "2. Arranca con un gancho que enganche en los primeros 2 segundos.\n"
    "3. Termina con un cierre o call-to-action breve.\n"
    "4. Sin emojis, sin rótulos, solo el texto que se va a narrar.\n\n"
    "Responde SOLO con JSON:\n"
    '{{"title": "<título efectivo y concreto>", "hook": "<gancho máx 60 caracteres>", '
    '"script": "<oración. Oración. Oración.>", "tags": ["tag1", "tag2"]}}'
)


def _parse_script_json(content: str) -> dict:
    cleaned = re.sub(r"```[\s\S]*?```", "", content).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("no JSON object found in LLM response")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    script = str(data.get("script", "")).strip()
    if len(script) < 10:
        raise ValueError("LLM returned an empty script")
    return {
        "title": str(data.get("title", ""))[:100],
        "hook": str(data.get("hook", ""))[:70],
        "script": script,
        "tags": [str(t).lower().strip() for t in (data.get("tags") or [])][:15],
    }


def _script_sentences(script: str) -> list[str]:
    parts = re.split(r"(?<=[.!?¿¡])\s+|(?<=[.!?¿¡])(?=\"|\')", script)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences[:12]


def write_script(prompt: str, duration: float, style: str, platform: str) -> dict:
    """Guion LLM para el prompt; fallback determinístico si no hay clave o falla."""
    platform_names = {
        "youtube_shorts": "YouTube Shorts",
        "youtube": "YouTube (video largo)",
        "tiktok": "TikTok",
        "facebook_reels": "Facebook Reels",
        "instagram_reels": "Instagram Reels",
    }
    pname = platform_names.get(platform, platform)
    words = max(10, int(duration * WORD_RATE))
    try:
        content = _complete(
            _SCRIPT_SYSTEM,
            _SCRIPT_PROMPT.format(
                platform=pname, duration=duration, style=style or "professional",
                prompt=prompt, words=words, mins={"min": 2, "max": 9},
            ),
        )
        if content:
            info = _parse_script_json(content)
            info["sentences"] = _script_sentences(info["script"])
            logger.info("script generado por LLM: %d palabras (%s)", len(info["script"].split()), info["title"][:60])
            return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("guion LLM FAILED (%s); usando fallback determinístico", exc)

    sentences = _script_sentences(prompt)
    cleaned = " ".join(prompt.split())
    return {
        "title": cleaned[:80] or "Momento clave",
        "hook": cleaned[:70] or prompt[:70],
        "script": cleaned,
        "sentences": sentences if sentences else [cleaned],
        "tags": ["video", "generado", "contenido", "ia"],
    }


# ── TTS (voz) ───────────────────────────────────────────────


async def _edge_tts_save(text: str, voice: str, out: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out))


def build_voiceover(text: str, voice: str | None, out: Path) -> str | None:
    """Edge-TTS con respaldo gTTS; sin voz si ambos fallan o no están instalados."""
    target = _resolve_voice(voice)
    try:
        asyncio.run(_edge_tts_save(text, target, out))
        if out.exists() and out.stat().st_size > 0:
            logger.info("voz edge-tts OK (%s)", target)
            return str(out)
        raise RuntimeError("edge-tts devolvió archivo vacío")
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge-tts FAILED (%s); probando gTTS", exc)
    try:
        from gtts import gTTS

        gTTS(text=text, lang="es", slow=False).save(str(out))
        if out.exists() and out.stat().st_size > 0:
            logger.info("voz gTTS OK")
            return str(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gTTS FAILED (%s); video sin voz", exc)
    return None


# ── Visuales (Pillow + ffmpeg) ──────────────────────────────


def _size_for(platform: str | None) -> tuple[int, int]:
    if platform == "youtube":
        return 1920, 1080  # horizontal (video largo)
    return 1080, 1920  # vertical (Shorts/TikTok/Reels)


def _load_font(size: int):
    from PIL import ImageFont

    font = _find_font()
    try:
        if font:
            return ImageFont.truetype(font, size)
        return ImageFont.load_default(size=size)
    except Exception:  # noqa: BLE001
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _wrap_measure(draw, text: str, fnt, max_w: int) -> list[str]:
    """Envuelve `text` en líneas que no superen max_w píxeles (por palabras)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=fnt) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _render_background(size: tuple[int, int], style: str, title: str, out: Path) -> Path:
    """Fondo gradiente vertical (2× para margen del zoom) + gancho en MAYÚSCULAS."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    w, h = base_w * 2, base_h * 2
    top, bottom, accent = _STYLE_PALETTES.get(style or "professional", _STYLE_PALETTES["professional"])
    c_top, c_bottom = _hex_to_rgb(top), _hex_to_rgb(bottom)

    img = Image.new("RGB", (w, h), c_top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        draw.line([(0, y), (w, y)], fill=_lerp(c_top, c_bottom, y / max(1, h - 1)))

    # banda diagonal translúcida con el acento marcador
    band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    alpha = 26
    bd.polygon(
        [(0, int(h * 0.15)), (int(w * 0.42), 0), (int(w * 0.62), 0), (int(w * 0.20), int(h * 0.15))],
        fill=_hex_to_rgb(accent) + (alpha,),
    )
    bd.polygon(
        [(0, int(h * 0.52)), (int(w * 0.30), int(h * 0.34)), (int(w * 0.46), int(h * 0.34)), (int(w * 0.16), int(h * 0.52))],
        fill=_hex_to_rgb(accent) + (alpha,),
    )
    img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
    draw = ImageDraw.Draw(img)

    # gancho principal en MAYÚSCULAS
    text = _emoji_strip(title).upper()[:80]
    max_w = int(w * 0.86)
    fontsize = int(base_w * 0.16)
    fnt = _load_font(fontsize)
    while fnt.size > int(base_w * 0.08):
        lines = _wrap_measure(draw, text, fnt, max_w)
        if all(draw.textlength(line, font=fnt) <= max_w for line in lines) and len(lines) <= 3:
            break
        fnt = _load_font(fnt.size - 8)
    lines = _wrap_measure(draw, text, fnt, max_w)[:3]
    line_h = int(fnt.size * 1.12)
    total_h = line_h * len(lines)
    x0 = int(w * 0.07)
    y0 = int(h * 0.30) - total_h // 2
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=fnt)
        # subrayado marcador amarillo debajo del texto
        draw.rectangle(
            [int(x0 + tw + 14), y0 + int(fnt.size * 0.92), int(x0 + tw + 24), y0 + int(fnt.size * 1.04)],
            fill=_hex_to_rgb(accent) + (255,),
        )
        draw.text((x0, y0), line, font=fnt, fill="white",
                  stroke_width=max(2, int(fnt.size * 0.06)), stroke_fill=(0, 0, 0))
        y0 += line_h

    # etiqueta edgetape discreta
    tag_fnt = _load_font(max(14, int(base_w * 0.028)))
    tag = "edgetape · GENERADO CON IA"
    tag_w = draw.textlength(tag, font=tag_fnt)
    draw.text((w - tag_w - int(w * 0.05), h - int(base_h * 0.09)), tag,
              font=tag_fnt, fill=_hex_to_rgb(accent) + (200,))

    img.save(out, "PNG")
    return out


def _render_captions(
    sentences: list[str], starts: list[float], ends: list[float],
    size: tuple[int, int], out_dir: Path,
) -> list[Path]:
    """Tarjetas de subtítulo (PNG RGBA) sincronizadas a cada oración."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    paths: list[Path] = []
    for i, sentence in enumerate(sentences):
        out = out_dir / f"cap_{i}.png"
        img = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        text = _emoji_strip(sentence)[:160]
        max_w = int(base_w * 0.84)
        fontsize = int(base_w * 0.052)
        fnt = _load_font(fontsize)
        while fnt.size > int(base_w * 0.034):
            lines = _wrap_measure(d, text, fnt, max_w)
            if all(d.textlength(l, font=fnt) <= max_w for l in lines) and len(lines) <= 3:
                break
            fnt = _load_font(fnt.size - 4)
        lines = _wrap_measure(d, text, fnt, max_w)[:3]
        line_h = int(fnt.size * 1.18)
        box_w = max_w + int(base_w * 0.05)
        box_h = line_h * len(lines) + int(base_h * 0.045)
        bx = (base_w - box_w) // 2
        by = int(base_h * 0.68)
        d.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=int(base_h * 0.012),
                            fill=(6, 12, 28, 190))
        d.rectangle([bx, by, bx + int(base_w * 0.012), by + box_h], fill=_hex_to_rgb(_MARK) + (255,))
        ty = by + int(base_h * 0.022)
        for line in lines:
            tw = d.textlength(line, font=fnt)
            d.text(((base_w - tw) / 2, ty), line, font=fnt, fill="white",
                   stroke_width=1, stroke_fill=(0, 0, 0))
            ty += line_h
        img.save(out, "PNG")
        paths.append(out)
    return paths


def _sentence_timings(sentences: list[str], total: float) -> tuple[list[float], list[float]]:
    weights = [max(1.0, float(len(s.split()))) for s in sentences]
    if len(sentences) == 1:
        return [0.0], [total]
    scale = total / sum(weights)
    segs = [max(1.2, w * scale) for w in weights]
    s = sum(segs)
    if s > total:
        segs = [x * total / s for x in segs]
    starts: list[float] = []
    ends: list[float] = []
    cur = 0.0
    for j, seg in enumerate(segs):
        starts.append(cur)
        cur += seg
        ends.append(cur if j < len(segs) - 1 else total)
    return starts, ends


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg ai render failed: {result.stderr.strip()}")


def render_video(
    bg: Path,
    captions: list[Path],
    audio: str | None,
    starts: list[float],
    ends: list[float],
    size: tuple[int, int],
    total: float,
    out: str | Path,
    workdir: str | Path | None = None,
) -> Path:
    """Ensambla el video final en DOS pasadas (el render en una sola pasada con
    todas las entradas en bucle infinito se estanca en frame 0 en ffmpeg):

    1. zoom suave (Ken Burns) sobre el fondo → base.mp4
    2. subtítulos (overlay con enable) + voz sobre la base → archivo final.
    """
    w, h = size
    tmp_dir = Path(workdir) if workdir else Path(out).parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    base = tmp_dir / "_base.mp4"

    # Paso 1: fondo con zoompan (Ken Burns).
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", f"{total:.3f}", "-i", str(bg),
        "-filter_complex",
        f"zoompan=z='min(zoom+0.0006,1.12)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30,format=yuv420p",
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-f", "mp4", str(base),
    ])

    # Paso 2: subtítulos + audio sobre la base (entrada 0 acotada: sin deadlock).
    inputs: list[str] = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(base)]
    for cap, st, en in zip(captions, starts, ends):
        seg = max(0.5, en - st)
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{seg:.3f}", "-i", str(cap)]
    audio_idx = 1 + len(captions)
    if audio:
        inputs += ["-i", audio]

    parts: list[str] = []
    prev = "0:v"
    for i in range(len(captions)):
        parts.append(f"[{i + 1}:v]format=rgba[c{i}]")
        parts.append(
            f"[{prev}][c{i}]overlay=0:0:enable='between(t,{starts[i]:.2f},{ends[i]:.2f})'[v{i}]"
        )
        prev = f"v{i}"
    parts.append(f"[{prev}]format=yuv420p[vout]")
    if audio:
        parts.append(f"[{audio_idx}:a]aresample=48000[a]")

    cmd = list(inputs) + ["-filter_complex", ";".join(parts), "-map", "[vout]"]
    if audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart",
            "-t", f"{total:.3f}", "-f", "mp4", str(out)]
    _run_ffmpeg(cmd)

    if not Path(out).exists():
        raise RuntimeError("ffmpeg ai render no produjo archivo")
    return Path(out)


# ── Entrada usada por el pipeline ───────────────────────────


def generate_ai_video(meta: dict, meta_path: Path | None, source: str | Path, tmp: Path) -> dict:
    """Genera el video de origen a partir de generate_meta.json.

    Devuelve el guion (title/hook/script/sentences/tags) para construir el clip, y
    lo persiste también en `meta["script_gen"]` del propio generate_meta.json.
    """
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    prompt = (meta.get("prompt") or "").strip() or "Video generado con IA"
    duration = max(1.0, float(meta.get("duration", 30)))
    platform = meta.get("platform") or "youtube_shorts"
    style = meta.get("style") or "professional"
    voice = meta.get("voice")

    script_info = write_script(prompt, duration, style, platform)
    script_text = script_info["script"]
    logger.info("guion para IA (%.0fs): %d caracteres", duration, len(script_text))

    audio = None
    audio_path = tmp / "voice.mp3"
    try:
        audio = build_voiceover(script_text, voice, audio_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS inesperado: %s", exc)
        audio = None

    audio_dur = 0.0
    if audio:
        try:
            audio_dur = probe_duration(audio)
        except Exception:  # noqa: BLE001
            audio_dur = 0.0
    total = max(duration, audio_dur)
    if total <= 0.5:
        total = duration

    size = _size_for(platform)
    bg = _render_background(size, style, script_info["hook"] or prompt, tmp / "bg.png")
    starts, ends = _sentence_timings(script_info["sentences"], total)
    captions = _render_captions(script_info["sentences"], starts, ends, size, tmp)
    render_video(bg, captions, audio, starts, ends, size, total, source, workdir=tmp)

    if meta_path is not None:
        try:
            stored = json.loads(meta_path.read_text(encoding="utf-8"))
            stored["script_gen"] = script_info
            meta_path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    return script_info