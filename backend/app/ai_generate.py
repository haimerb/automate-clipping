from __future__ import annotations

"""Generación procedimental de video con IA como origen: el LLM escribe el guion
y las keywords visuales de cada escena, el TTS (edge-tts → gTTS) lo narra y
ffmpeg monta un video profesional por escenas: tarjeta de título animada, un clip
de b-roll real con movimiento (Pexels/Pixabay) o una imagen con efecto Ken
Burns/paneo, fades, subtítulos lower-third con chip de keywords y música de fondo
opcional — vertical (Shorts/Reels/TikTok) u horizontal (YouTube video largo).

Degradación en cascada (nunca queda mudo):
- sin LLM → el prompt es el guion (keywords derivadas del texto);
- sin TTS → el video sale sin voz (con música si se pidió);
- sin b-roll → fotos de stock → material generado por IA (opcional) → Wikimedia
  → fondos de marca variados;
- si el render por escenas falla → el render legacy de un solo fondo;
- cada degradación se registra en `warnings` y viaja al job (no falla en silencio);
- si todo falla → el pipeline cae al mock de ffmpeg.
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

from . import materials
from . import videogen
from .media import FFMPEG, FFPROBE, _emoji_strip, _find_font, probe_duration
from .scorer import _content_words

logger = logging.getLogger(__name__)

# Duraciones aceptadas por /api/generate. Los verticales mantienen sus límites reales
# de publicación (lea scorer.FORMAT_LIMITS: shorts/tiktok ≤60, reels ≤90); YouTube
# (video largo) ofrece de 6 a 15 minutos.
GENERATE_DURATIONS = [15, 30, 60, 90, 120, 180, 360, 420, 480, 540, 600, 660, 720, 780, 840, 900]

# Piso del formato largo de YouTube (no se ofrecen longs de menos de 6 minutos).
YOUTUBE_MIN_LONG = 360.0

DEFAULT_VOICE = "es-MX-DaliaNeural"

# ~2.6 palabras/segundo en español hablado medio
WORD_RATE = 2.6

# Una escena (oración + imagen) por ~40s de video, entre 4 y 20; tope de oraciones.
SCENES_EVERY = 40.0
SCENES_MIN = 4
SCENES_MAX = 20
SCENES_MAX_SENTENCES = 36

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
    "Divide el guion en oraciones separadas por punto; cada oración será una "
    "escena del video, así que frases breves, autónomas y fáciles de acompañar "
    "con una imagen. "
    "Para cada oración produce además una 'query' visual en INGLÉS de 2 a 4 "
    "palabras (sustantivos concretos y filmables, sin nombres propios ni marcas, "
    "sin texto) para buscar b-roll de stock que ilustre esa escena. "
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


def _scene_count(duration: float) -> int:
    return max(SCENES_MIN, min(SCENES_MAX, round(duration / SCENES_EVERY)))


_SCRIPT_PROMPT = (
    "Plataforma objetivo: {platform}\n"
    "Duración del video: {duration:.0f} segundos\n"
    "Estilo: {style}\n\n"
    "Tema: {prompt}\n\n"
    "Instrucciones:\n"
    "1. Guion narrado en español de ≈{words} palabras, dividido en {nscenes} "
    "oraciones cortas para locución (una oración = una escena).\n"
    "2. Arranca con un gancho que enganche en los primeros 2 segundos.\n"
    "3. Termina con un cierre o call-to-action breve.\n"
    "4. Sin emojis, sin rótulos, solo el texto que se va a narrar.\n"
    "5. Devuelve 'queries': una keyword visual EN INGLÉS (2-4 palabras, "
    "concreta y filmable) por cada oración, en el MISMO orden.\n\n"
    "Responde SOLO con JSON:\n"
    '{{"title": "<título efectivo y concreto>", "hook": "<gancho máx 60 caracteres>", '
    '"script": "<oración. Oración. Oración.>", "tags": ["tag1", "tag2"], '
    '"queries": ["city skyline", "happy family", "..."]}}'
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
    queries = [
        " ".join(str(q).split())[:60]
        for q in (data.get("queries") or [])
        if str(q).strip()
    ]
    return {
        "title": str(data.get("title", ""))[:100],
        "hook": str(data.get("hook", ""))[:70],
        "script": script,
        "tags": [str(t).lower().strip() for t in (data.get("tags") or [])][:15],
        "queries": queries,
    }


def _script_sentences(script: str) -> list[str]:
    parts = re.split(r"(?<=[.!?¿¡])\s+|(?<=[.!?¿¡])(?=\"|\')", script)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences[:SCENES_MAX_SENTENCES]


def _topic_phrase(prompt: str) -> str:
    cleaned = " ".join(prompt.split())
    for pat in (r"titulado\s*[:“\"']?\s*([^“\"'\n.]+)\s*[”\"']?",
                r"título\s*[:“\"']?\s*([^“\"'\n.]+)\s*[”\"']?",
                r"titulada\s*[:“\"']?\s*([^“\"'\n.]+)\s*[”\"']?",
                r"sobre\s+([^,.\n;]+)"):
        m = re.search(pat, cleaned, re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return cleaned[:90] or "un tema"


def _fallback_script(prompt: str, duration: float) -> dict:
    """Guion determinístico de respaldo. Cuando el LLM no está disponible hay que
    cubrir la duración completa (p. ej. 6-15 min de YouTube), así que expande el
    prompt a ≈ WORD_RATE palabras por segundo y extrae un título decente."""
    topic = _topic_phrase(prompt)
    target_words = max(24, int(duration * WORD_RATE))
    sentences: list[str] = []
    sentences.append(
        f"¿Sabés qué hace tan especial a {topic}? Hoy te lo cuento de punta a punta."[:160]
    )
    parts = [
        "Para entender bien la historia hay que mirar el origen: {t} es mucho más que lo que parece a simple vista.",
        "Lo primero que marca la diferencia son los detalles que casi nadie nota, y en {t} hay muchísimos.",
        "Con el correr de los años, {t} fue ganando protagonismo hasta convertirse en un tema del que todos hablan.",
        "Hay momentos que quedaron grabados en la memoria colectiva, y {t} tiene varios de esos momentos.",
        "Hablemos de datos concretos: lo que pasó en {t} cambió la forma de ver las cosas.",
        "A veces conviene frenar un segundo y preguntarse por qué {t} resonó tanto entre la gente.",
        "Los protagonistas de {t} no lo hicieron solos: detrás hubo decisiones, esfuerzo y mucha constancia.",
        "Es difícil resumir todo lo que representa {t}, pero vale la pena intentarlo.",
        "Cada tanto aparece una historia que redefine lo que creíamos saber sobre {t}.",
        "Y ese es justamente el punto: {t} demuestra que lo importante no es la fama, sino el impacto real.",
    ]
    idx = 0
    while _word_count(sentences) < target_words and len(sentences) < SCENES_MAX_SENTENCES - 1:
        sentences.append(parts[idx % len(parts)].format(t=topic))
        idx += 1
    sentences.append(
        f"Así que ya sabés: si querés entender {topic}, mirá los detalles y dejate llevar por la historia."
    )
    script = " ".join(sentences)
    title = _topic_phrase(prompt)
    queries = [_scene_query(s) or topic[:40] for s in sentences]
    return {
        "title": title[:100],
        "hook": sentences[0][:70],
        "script": script,
        "sentences": _script_sentences(script),
        "tags": ["video", "generado", "contenido", "ia"],
        "queries": queries,
    }


def _word_count(text: str) -> int:
    return len(str(text).split())


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
    nscenes = _scene_count(duration)
    try:
        content = _complete(
            _SCRIPT_SYSTEM,
            _SCRIPT_PROMPT.format(
                platform=pname, duration=duration, style=style or "professional",
                prompt=prompt, words=words, nscenes=nscenes,
            ),
        )
        if content:
            info = _parse_script_json(content)
            info["sentences"] = _script_sentences(info["script"])
            logger.info(
                "script generado por LLM: %d palabras, %d escenas (%s)",
                len(info["script"].split()), len(info["sentences"]), info["title"][:60],
            )
            return info
    except Exception as exc:  # noqa: BLE001
        logger.warning("guion LLM FAILED (%s); usando fallback determinístico", exc)

    pb = _fallback_script(prompt, duration)
    return {
        "title": pb["title"] or "Momento clave",
        "hook": pb["hook"],
        "script": pb["script"],
        "sentences": pb["sentences"],
        "tags": ["video", "generado", "contenido", "ia"],
        "queries": pb.get("queries", []),
    }


# ── TTS (voz) ───────────────────────────────────────────────


def _pad_audio(audio: str, total: float, out: Path) -> str | None:
    """Estira el audio con silencio hasta `total` segundos (apad)."""
    try:
        cmd = [
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-i", audio, "-af", "aresample=48000,apad",
            "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "128k", "-f", "mp4", str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return str(out)
    except Exception:  # noqa: BLE001
        pass
    return None


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


def _paint_gradient(w: int, h: int, style: str):
    """Fondo con gradiente vertical de marca + bandas diagonales translúcidas."""
    from PIL import Image, ImageDraw

    top, bottom, accent = _STYLE_PALETTES.get(style or "professional", _STYLE_PALETTES["professional"])
    c_top, c_bottom = _hex_to_rgb(top), _hex_to_rgb(bottom)

    img = Image.new("RGB", (w, h), c_top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        draw.line([(0, y), (w, y)], fill=_lerp(c_top, c_bottom, y / max(1, h - 1)))

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
    return Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")


def _render_background(size: tuple[int, int], style: str, title: str, out: Path) -> Path:
    """Tarjeta de título: gradiente de marca 2× + gancho en MAYÚSCULAS."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    w, h = base_w * 2, base_h * 2
    accent = _STYLE_PALETTES.get(style or "professional", _STYLE_PALETTES["professional"])[2]
    img = _paint_gradient(w, h, style)
    draw = ImageDraw.Draw(img)

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


def _render_end_card(size: tuple[int, int], style: str, title: str | None, out: Path) -> Path:
    """Cierre: gradiente de marca con call-to-action y título del video."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    w, h = base_w * 2, base_h * 2
    accent = _STYLE_PALETTES.get(style or "professional", _STYLE_PALETTES["professional"])[2]
    img = _paint_gradient(w, h, style)
    draw = ImageDraw.Draw(img)

    cta = "SEGUÍ · COMENTÁ · COMPARTÍ"
    max_w = int(w * 0.86)
    fnt_cap = _load_font(int(base_w * 0.085))
    fnt_cta = _load_font(int(base_w * 0.10))
    y = int(h * 0.36)

    if title:
        cap = _emoji_strip(title).upper()[:80]
        lines = _wrap_measure(draw, cap, fnt_cap, max_w)[:3]
        line_h = int(fnt_cap.size * 1.14)
        for line in lines:
            tw = draw.textlength(line, font=fnt_cap)
            draw.rectangle(
                [int(w * 0.07) + tw + 14, y + int(fnt_cap.size * 0.92), int(w * 0.07) + tw + 24, y + int(fnt_cap.size * 1.04)],
                fill=_hex_to_rgb(accent) + (255,),
            )
            draw.text((int(w * 0.07), y), line, font=fnt_cap, fill="white",
                      stroke_width=2, stroke_fill=(0, 0, 0))
            y += line_h
    y += int(base_h * 0.03)
    ctw = draw.textlength(cta, font=fnt_cta)
    draw.text(((w - ctw) / 2, y), cta, font=fnt_cta, fill=_hex_to_rgb(accent) + (255,),
              stroke_width=2, stroke_fill=(10, 12, 24))

    tag_fnt = _load_font(max(14, int(base_w * 0.028)))
    tag = "edgetape"
    tag_w = draw.textlength(tag, font=tag_fnt)
    draw.text((w - tag_w - int(w * 0.05), h - int(base_h * 0.09)), tag,
              font=tag_fnt, fill=_hex_to_rgb(accent) + (200,))

    img.save(out, "PNG")
    return out


def _render_scene_gradient(size: tuple[int, int], style: str, variant: int, out: Path) -> Path:
    """Fondo de marca para escenas sin imagen (pasa las fallas por distintos matices)."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    w, h = base_w * 2, base_h * 2
    accent = _STYLE_PALETTES.get(style or "professional", _STYLE_PALETTES["professional"])[2]
    img = _paint_gradient(w, h, style)
    band = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    if variant % 2 == 0:
        pts = [(int(w * 0.15), h), (0, int(h * 0.55)), (0, int(h * 0.75)), (int(w * 0.30), h)]
    else:
        pts = [(w, int(h * 0.05)), (int(w * 0.62), 0), (int(w * 0.42), 0), (w, int(h * 0.25))]
    bd.polygon(pts, fill=_hex_to_rgb(accent) + (22,))
    img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
    img.save(out, "PNG")
    return out


def _cover_crop(img, target: tuple[int, int]):
    from PIL import Image

    tw, th = target
    scale = max(tw / img.width, th / img.height)
    nw, nh = round(img.width * scale), round(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = (nh - th) // 2
    return img.crop((x, y, x + tw, y + th))


def _darken(img, alpha: int = 66):
    from PIL import Image

    overlay = Image.new("RGBA", img.size, (4, 8, 20, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _prepare_still(
    kind: str, image: Path | None, size: tuple[int, int], style: str,
    info: dict, scene_i: int, tmp: Path,
) -> Path:
    """Imagen quieta 2× (margen para el Ken Burns) de una escena."""
    if kind == "title":
        return _render_background(size, style, info.get("hook") or info.get("title") or "Video generado con IA", tmp / f"still_title{scene_i}.png")
    if kind == "end":
        return _render_end_card(size, style, info.get("title"), tmp / f"still_end{scene_i}.png")
    if image is not None:
        try:
            from PIL import Image

            img = Image.open(image).convert("RGB")
            img = _cover_crop(img, (size[0] * 2, size[1] * 2))
            img = _darken(img, 66)
            p = tmp / f"still_img{scene_i}.jpg"
            img.save(p, "JPEG", quality=88)
            return p
        except Exception:  # noqa: BLE001
            logger.warning("imagen de escena %d ilegible; gradiente de marca", scene_i)
    return _render_scene_gradient(size, style, scene_i, tmp / f"still_grad{scene_i}.png")


# ── Imágenes por escena (Wikimedia Commons) ──────────────────

_WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
# Wikimedia bloquea agentes genéricos (python-httpx) con 403; exige un UA descriptivo.
_UA = "edgetape-automate-clipping/1.0 (video clipping automation; +https://github.com/haimerb/automate-clipping)"


def _scene_query(text: str, limit: int = 3) -> str:
    words = list(dict.fromkeys(_content_words(text)))
    return " ".join(w[:18] for w in words[:limit])


def _pick_image_info(pages: dict, want_landscape: bool) -> str | None:
    for page in pages.values():
        ii = (page.get("imageinfo") or [None])[0]
        if not ii:
            continue
        if ii.get("mime") not in _IMAGE_MIMES:
            continue
        w = int(ii.get("width") or 0)
        h = int(ii.get("height") or 0)
        if w < 640 or h < 640:
            continue
        if (want_landscape and h > w) or (not want_landscape and w > h):
            continue
        url = ii.get("thumburl") or ii.get("url")
        if url:
            return url
    return None


def _fetch_wikimedia_images(
    sentences: list[str], size: tuple[int, int], tmp: Path,
    max_total: float = 45.0, per_request: float = 10.0, client: httpx.Client | None = None,
) -> list[Path | None]:
    """Intenta una imagen real por oración; sin red/resultados → [None]*n (nunca rompe)."""
    n = len(sentences)
    if os.environ.get("EDGETAPE_AI_IMAGES", "1") == "0" or n <= 1:
        return [None] * n
    want_landscape = size[0] >= size[1]
    paths: list[Path | None] = [None] * n
    own = client is None
    try:
        c = client or httpx.Client(timeout=per_request, headers={"User-Agent": _UA})
        try:
            deadline = time.monotonic() + max_total
            for i, text in enumerate(sentences):
                if i == 0 or (i == n - 1 and n > 1):
                    continue  # título y cierre usan tarjetas de marca
                if time.monotonic() > deadline:
                    break
                words = list(dict.fromkeys(_content_words(text)))[:6]
                if not words:
                    continue
                url = None
                for k in (3, 2, 1):
                    query = " ".join(w[:18] for w in words[:k])
                    params = {
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": f"{query} filetype:bitmap",
                        "gsrnamespace": "6",
                        "gsrlimit": "6",
                        "prop": "imageinfo",
                        "iiprop": "url|size|mime",
                        "iiurlwidth": "1600",
                        "format": "json",
                        "origin": "*",
                    }
                    resp = c.get(_WIKIMEDIA_API, params=params)
                    resp.raise_for_status()
                    pages = resp.json().get("query", {}).get("pages", {})
                    url = _pick_image_info(pages, want_landscape)
                    if url:
                        break
                if not url:
                    continue
                image = c.get(url)
                if image.status_code != 200:
                    continue
                p = tmp / f"scene_{i}.img"
                p.write_bytes(image.content)
                if p.stat().st_size < 1024:
                    p.unlink()
                    continue
                paths[i] = p
                logger.info("escena %d: imagen de Wikimedia · %s", i, query)
        finally:
            if own:
                c.close()
    except Exception as exc:  # noqa: BLE001 — offline / timeouts / 429
        logger.warning("imágenes por escena fuera de servicio (%s); gradientes de marca", exc)
        return [None] * n
    return paths


def _fetch_scene_images(
    sentences: list[str], size: tuple[int, int], tmp: Path,
    max_total: float = 45.0, per_request: float = 10.0,
) -> list[Path | None]:
    """Compatibilidad: imágenes Wikimedia por oración (sin b-roll de stock)."""
    return _fetch_wikimedia_images(sentences, size, tmp, max_total, per_request)


def _try_videogen(
    pending: list[int],
    sentences: list[str],
    queries: list[str] | None,
    size: tuple[int, int],
    tmp: Path,
    assets: list[tuple[Path | None, bool]],
) -> list[int]:
    """Rellena con material generado por IA las escenas donde el stock falló.

    Va DESPUÉS del stock (gratis) y ANTES de Wikimedia. Es un proveedor de pago,
    así que se limita a `EDGETAPE_VIDEOGEN_MAX_SCENES` escenas (1 por defecto)
    para no quemar cuota. Nunca lanza: cualquier fallo cae a Wikimedia.
    """
    if not videogen.is_configured() or os.environ.get("EDGETAPE_VIDEOGEN", "1") == "0":
        return pending
    try:
        budget = max(0, int(os.environ.get("EDGETAPE_VIDEOGEN_MAX_SCENES", "1")))
    except ValueError:
        budget = 1
    if budget <= 0:
        return pending
    for i in pending[:budget]:
        prompt = (queries[i] if queries and i < len(queries) else "") or _scene_query(sentences[i])
        if not prompt:
            continue
        path, is_video = videogen.generate_asset(prompt, size, tmp / f"scene_{i}.asset")
        if path is not None:
            assets[i] = (path, is_video)
            logger.info("escena %d: material generado por IA · %s", i, prompt[:60])
    return [i for i in pending if assets[i][0] is None]


def _fetch_scene_media(
    sentences: list[str], queries: list[str] | None, size: tuple[int, int], tmp: Path,
    max_total: float = 90.0, per_request: float = 12.0,
) -> list[tuple[Path | None, bool]]:
    """Material por escena: b-roll real de stock (video > foto) y respaldo Wikimedia.

    Devuelve (ruta, es_video) por oración; la ruta va SIN extensión (se re-probea).
    Nunca lanza: sin red/claves deja escenas en None para usar fondos de marca.
    """
    n = len(sentences)
    if os.environ.get("EDGETAPE_AI_IMAGES", "1") == "0" or n <= 1:
        return [(None, False)] * n
    want_landscape = size[0] >= size[1]
    assets: list[tuple[Path | None, bool]] = [(None, False)] * n
    library = materials.build_library()

    with httpx.Client(timeout=per_request, headers={"User-Agent": _UA}) as client:
        deadline = time.monotonic() + max_total
        if library is not None:
            for i in range(1, n - 1 if n > 1 else n):
                if time.monotonic() > deadline:
                    logger.warning("tiempo de búsqueda de b-roll agotado en la escena %d", i)
                    break
                q = (
                    (queries[i] if queries and i < len(queries) else "")
                    or _scene_query(sentences[i])
                )
                if not q:
                    continue
                pick = library.take(library.search(q, want_landscape, client=client))
                if pick is None:
                    continue
                dest = tmp / f"scene_{i}.asset"
                if materials.download(client, pick, dest):
                    assets[i] = (dest, pick.kind == "video")
                    logger.info("escena %d: %s %s · %s", i, pick.provider, pick.kind, q)

        pending = [
            i for i in range(n)
            if assets[i][0] is None and i != 0 and not (i == n - 1 and n > 1)
        ]
        if pending:
            pending = _try_videogen(pending, sentences, queries, size, tmp, assets)
        if pending:
            images = _fetch_wikimedia_images(
                sentences, size, tmp,
                max_total=max(5.0, deadline - time.monotonic()), client=client,
            )
            for i in pending:
                if images[i] is not None:
                    assets[i] = (images[i], False)
    return assets


# ── Montaje (ffmpeg) ────────────────────────────────────────


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        err = result.stderr.strip()[-2000:]
        if result.returncode < 0:
            err = f"{err} (terminado por señal {result.returncode} — probable falta de memoria)"
        raise RuntimeError(f"ffmpeg ai render failed (rc={result.returncode}): {err}")


def _render_segment(still: Path, dur: float, variant: int, size: tuple[int, int], out: Path) -> None:
    """Ken Burns (zoom/paneo alternando) + fade in/out a negro por escena."""
    w, h = size
    frames = max(1, int(round(dur * 30.0)))
    if variant % 3 == 1:
        z, x = "1.15", f"(iw-iw/1.15)*on/{frames}"
    elif variant % 3 == 2:
        z, x = "1.15", f"(iw-iw/1.15)*(1-on/{frames})"
    else:
        z, x = "min(zoom+0.0006,1.15)", "iw/2-(iw/zoom/2)"
    y = "ih/2-(ih/zoom/2)" if variant % 3 == 0 else "ih/2-(ih/1.15/2)"
    zoom = f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps=30"
    filters = zoom
    if dur > 1.6:
        filters += f",fade=t=in:st=0:d=0.5,fade=t=out:st={max(0.0, dur - 0.5):.2f}:d=0.5"
    filters += ",format=yuv420p"
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(still),
        "-vf", filters, "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast",
        "-f", "mp4", str(out),
    ])


def _render_segment_video(
    clip: Path, dur: float, variant: int, size: tuple[int, int], out: Path
) -> None:
    """Escena con b-roll real: escala/recorta al formato, loopea y funde.

    Se silencia el audio del clip y se limita la duración a la escena; el
    `-stream_loop -1` garantiza movimiento aunque el clip sea más corto.
    """
    w, h = size
    filters = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
        "setsar=1",
    ]
    if variant % 2 == 1:
        filters.append("hflip")  # variedad sutil entre escenas consecutivas
    if dur > 1.6:
        filters.append(f"fade=t=in:st=0:d=0.5")
        filters.append(f"fade=t=out:st={max(0.0, dur - 0.5):.2f}:d=0.5")
    filters.append("format=yuv420p")
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(clip),
        "-an", "-vf", ",".join(filters), "-r", "30", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast",
        "-f", "mp4", str(out),
    ])


def _compose_scenes(
    segs: list[Path], captions: list[Path | None], audio: str | None,
    starts: list[float], ends: list[float], size: tuple[int, int],
    total: float, out: str | Path,
) -> Path:
    """Composición final POR ESCENA y concat con `-c copy`.

    Ensamblar un video de 6-15 min en un solo ffmpeg (base + varios bucles de
    caption + re-encode) desborda la memoria en máquinas limitadas (OOM → SIGKILL
    con rc -9 y stderr vacío). Aquí cada escena es un mp4 corto propio (memoria
    acotada) y el resultado se concatena por demuxer.
    """
    tmp = segs[0].parent if segs else Path(out).parent
    comps: list[Path] = []
    for i, seg in enumerate(segs):
        st = starts[i]
        en = ends[i]
        dur = max(0.5, en - st)
        inputs = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(seg)]
        cap_path = captions[i] if i < len(captions) else None
        cap_idx = None
        if cap_path is not None:
            cap_idx = 1
            inputs += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", str(cap_path)]
        audio_idx = None
        if audio:
            audio_idx = cap_idx + 1 if cap_idx else 1
            inputs += ["-ss", f"{st:.3f}", "-t", f"{dur:.3f}", "-i", str(audio)]

        parts: list[str] = []
        prevv = "0:v"
        if cap_idx is not None:
            parts.append(f"[{cap_idx}:v]format=rgba[c{i}]")
            parts.append(f"[{prevv}][c{i}]overlay=0:0:enable='between(t,0,{dur:.3f})'[v{i}]")
            prevv = f"v{i}"
        parts.append(f"[{prevv}]format=yuv420p[vout]")
        if audio_idx is not None:
            parts.append(f"[{audio_idx}:a]aresample=48000[a{i}]")

        comp = tmp / f"_comp{i}.mp4"
        cmd = list(inputs) + ["-filter_complex", ";".join(parts), "-map", "[vout]"]
        if audio_idx is not None:
            cmd += ["-map", f"[a{i}]", "-c:a", "aac", "-b:a", "128k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-r", "30",
                "-t", f"{dur:.3f}", "-f", "mp4", str(comp)]
        _run_ffmpeg(cmd)
        comps.append(comp)

    if len(comps) == 1:
        comps[0].replace(Path(out))
        return Path(out)

    lst = tmp / "_concat.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in comps), encoding="utf-8")
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-f", "mp4", str(out),
    ])
    if not Path(out).exists():
        raise RuntimeError("ffmpeg ai render no produjo archivo")
    # Los `_comp*.mp4` y la lista de concat son del tamaño del video final: si
    # caen fuera de `ai_tmp` nunca se limpian y cada job ocupa el doble.
    for leftover in [*comps, lst]:
        leftover.unlink(missing_ok=True)
    return Path(out)


def render_video(
    assets: list[Path], video_flags: list[bool], captions: list[Path | None], audio: str | None,
    starts: list[float], ends: list[float], size: tuple[int, int],
    total: float, out: str | Path, workdir: str | Path | None = None,
) -> Path:
    """Ensambla el video: b-roll/​Ken Burns + fade por escena → composición por
    escena (subtítulo + voz) → concat. Cada paso está acotado en memoria."""
    tmp_dir = Path(workdir) if workdir else Path(out).parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    segs: list[Path] = []
    for i, (asset, st, en) in enumerate(zip(assets, starts, ends)):
        dur = max(0.6, en - st)
        seg = tmp_dir / f"_seg{i}.mp4"
        if i < len(video_flags) and video_flags[i]:
            _render_segment_video(asset, dur, i, size, seg)
        else:
            _render_segment(asset, dur, i, size, seg)
        segs.append(seg)
    return _compose_scenes(segs, captions, audio, starts, ends, size, total, out)


def _render_legacy_single_bg(
    script_info: dict, sentences: list[str], audio: str | None,
    starts: list[float], ends: list[float], size: tuple[int, int],
    total: float, out: str | Path, tmp: Path,
) -> Path:
    """Respaldo al render previo (un solo fondo con subtítulos) si falla el de escenas."""
    bg = _render_background(size, "professional", script_info.get("hook") or script_info.get("title") or "", tmp / "bg.png")
    base = tmp / "_base.mp4"
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", f"{total:.3f}", "-i", str(bg),
        "-filter_complex",
        f"zoompan=z='min(zoom+0.0006,1.12)':d=1:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={size[0]}x{size[1]}:fps=30,format=yuv420p",
        "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-f", "mp4", str(base),
    ])
    caps = _render_captions(sentences, [None] * len(sentences), size, tmp)
    slices: list[Path] = []
    for i, (st, en) in enumerate(zip(starts, ends)):
        sl = tmp / f"_slice{i}.mp4"
        _run_ffmpeg([
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{st:.3f}", "-t", f"{max(0.5, en - st):.3f}", "-i", str(base),
            "-c:v", "copy", "-f", "mp4", str(sl),
        ])
        slices.append(sl)
    return _compose_scenes(slices, caps, audio, starts, ends, size, total, out)


# ── Subtítulos (lower-third) ────────────────────────────────


def _render_captions(
    sentences: list[str], keywords: list[str | None], size: tuple[int, int], out_dir: Path,
) -> list[Path]:
    """Tarjetas de subtítulo (PNG RGBA) sincronizadas a cada escena, con chip de keywords."""
    from PIL import Image, ImageDraw

    base_w, base_h = size
    paths: list[Path] = []
    for i, sentence in enumerate(sentences):
        out = out_dir / f"cap_{i}.png"
        img = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        text = _emoji_strip(sentence)[:160]
        max_w = int(base_w * 0.82)
        fontsize = int(base_w * 0.046)
        fnt = _load_font(fontsize)
        while fnt.size > int(base_w * 0.03):
            lines = _wrap_measure(d, text, fnt, max_w)
            if all(d.textlength(l, font=fnt) <= max_w for l in lines) and len(lines) <= 3:
                break
            fnt = _load_font(fnt.size - 4)
        lines = _wrap_measure(d, text, fnt, max_w)[:3]
        line_h = int(fnt.size * 1.16)
        box_w = max_w + int(base_w * 0.05)
        box_h = line_h * len(lines) + int(base_h * 0.05)
        bx = (base_w - box_w) // 2
        by = int(base_h * 0.70)
        d.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=int(base_h * 0.012),
                            fill=(6, 12, 28, 195))
        d.rectangle([bx, by, bx + int(base_w * 0.014), by + box_h], fill=_hex_to_rgb(_MARK) + (255,))

        kw = (keywords[i] or "").strip() if i < len(keywords) else ""
        if kw and len(kw) <= 28:
            chip_fnt = _load_font(int(base_w * 0.03))
            chip_txt = kw.upper()
            chip_w = int(d.textlength(chip_txt, font=chip_fnt) + base_w * 0.04)
            chip_h = int(base_h * 0.045)
            chip_y = by - chip_h - int(base_h * 0.014)
            d.rounded_rectangle(
                [bx + int(base_w * 0.02), chip_y, bx + int(base_w * 0.02) + chip_w, chip_y + chip_h],
                radius=int(chip_h / 2), fill=_hex_to_rgb(_MARK) + (255,),
            )
            d.text((bx + int(base_w * 0.04), chip_y + int(chip_h * 0.24)), chip_txt,
                   font=chip_fnt, fill=(10, 16, 40))

        ty = by + int(base_h * 0.024)
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


# ── Música de fondo (opcional) ───────────────────────────────

_MUSIC_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac"}
_MUSIC_NONE = {"", "none", "sin", "sin_musica", "sin música", "off", "no", "0"}


def music_dir() -> Path:
    """Carpeta de pistas: `EDGETAPE_MUSIC_DIR` o `backend/assets/music`."""
    raw = os.environ.get("EDGETAPE_MUSIC_DIR")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "assets" / "music"


def list_music_tracks() -> list[str]:
    """Nombres de archivo de las pistas disponibles (vacío si no hay carpeta)."""
    d = music_dir()
    if not d.is_dir():
        return []
    return sorted(
        p.name for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in _MUSIC_EXTS
    )


def _resolve_music(choice: str | None) -> Path | None:
    """Traduce la elección del usuario ("none" | "auto" | nombre de pista) a un archivo."""
    if choice is None:
        return None
    key = str(choice).strip()
    if key.lower() in _MUSIC_NONE:
        return None
    tracks = list_music_tracks()
    if not tracks:
        logger.warning("música solicitada pero no hay pistas en %s; se sigue sin música", music_dir())
        return None
    d = music_dir()
    if key.lower() == "auto":
        return d / random.choice(tracks)
    for name in tracks:
        if name == key or Path(name).stem.lower() == Path(key).stem.lower():
            return d / name
    logger.warning("pista '%s' no encontrada; se usa '%s'", key, tracks[0])
    return d / tracks[0]


def _mix_music(voice: str | None, total: float, music: Path, out: Path) -> str | None:
    """Mezcla la pista bajo la voz (o genera audio solo con música). Nunca lanza."""
    try:
        volume = os.environ.get("EDGETAPE_MUSIC_VOLUME", "0.22")
        if voice:
            inputs = ["-i", voice, "-stream_loop", "-1", "-i", str(music)]
        else:
            inputs = [
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-stream_loop", "-1", "-i", str(music),
            ]
        graph = (
            f"[1:a]volume={volume}[m];"
            "[0:a][m]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[a]"
        )
        _run_ffmpeg(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
             "-filter_complex", graph, "-map", "[a]", "-t", f"{total:.3f}",
             "-c:a", "aac", "-b:a", "128k", "-f", "mp4", str(out)],
            timeout=300,
        )
        if out.exists() and out.stat().st_size > 0:
            logger.info("música de fondo agregada: %s", music.name)
            return str(out)
    except Exception as exc:  # noqa: BLE001 — la música es opcional
        logger.warning("mezcla de música falló (%s); se deja solo la voz", exc)
    return None


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
    logger.info("guion para IA (%.0fs): %d caracteres, %d escenas",
                duration, len(script_text), len(script_info["sentences"]))

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
    if audio and audio_dur < total - 0.25:
        audio = _pad_audio(audio, total, tmp / "voice_padded.m4a") or audio
        audio_dur = total

    size = _size_for(platform)
    sentences = script_info["sentences"] or [script_text]
    starts, ends = _sentence_timings(sentences, total)

    n = len(sentences)
    queries = script_info.get("queries") or []
    warnings: list[str] = []
    assets = _fetch_scene_media(sentences, queries, size, tmp)
    video_count = sum(1 for _, is_v in assets if is_v)
    image_count = sum(1 for p, is_v in assets if p is not None and not is_v)
    if video_count or image_count:
        logger.info(
            "material por escena: %d b-roll, %d imágenes, %d fondos (%d escenas)",
            video_count, image_count, n - video_count - image_count, n,
        )
    else:
        warnings.append("sin material de stock ni imágenes; se usaron fondos de marca")
        logger.info("sin material por escena — gradientes de marca (%d escenas)", n)

    music_path = _resolve_music(meta.get("music"))
    if music_path is not None:
        mixed = _mix_music(audio, total, music_path, tmp / "voice_music.m4a")
        if mixed:
            audio = mixed
        else:
            warnings.append("no se pudo mezclar la música de fondo")

    info = {"title": script_info.get("title") or prompt, "hook": script_info.get("hook") or prompt}
    paths: list[Path] = []
    video_flags: list[bool] = []
    for i in range(n):
        path_i, is_video = assets[i]
        if is_video and path_i is not None:
            paths.append(path_i)
            video_flags.append(True)
        else:
            paths.append(_prepare_still(
                "title" if i == 0 else ("end" if (i == n - 1 and n > 1) else "body"),
                path_i, size, style, info, i, tmp,
            ))
            video_flags.append(False)

    keywords = [
        (_scene_query(sentences[i]) if (assets[i][0] is not None and not assets[i][1]) else "")
        for i in range(n)
    ]
    cap_pngs = _render_captions(sentences, keywords, size, tmp)
    overlays: list[Path | None] = [
        None if (i == 0 or (i == n - 1 and n > 1)) else cap_pngs[i]
        for i in range(n)
    ]

    try:
        render_video(paths, video_flags, overlays, audio, starts, ends, size, total, source, workdir=tmp)
    except Exception as exc:  # noqa: BLE001
        logger.warning("render por escenas FAILED (%s); reintentando con un solo fondo", exc)
        warnings.append("el montaje por escenas falló; se usó un único fondo animado")
        _render_legacy_single_bg(script_info, sentences, audio, starts, ends, size, total, source, tmp)

    try:
        rendered_dur = probe_duration(source)
        if rendered_dur <= 1.0:
            warnings.append("el video renderizado quedó vacío o demasiado corto")
    except Exception:  # noqa: BLE001
        warnings.append("no se pudo validar la duración del video renderizado")
    script_info["warnings"] = warnings

    if meta_path is not None:
        try:
            stored = json.loads(meta_path.read_text(encoding="utf-8"))
            stored["script_gen"] = script_info
            meta_path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    return script_info