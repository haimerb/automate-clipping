from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Protocol

import time

import httpx

from .scorer import _content_words

logger = logging.getLogger(__name__)

VIRAL_SYSTEM = (
    "Eres un experto en marketing de contenido viral para YouTube, TikTok y redes sociales. "
    "Generas títulos, descripciones y tags que maximizan views, engagement y shares. "
    "SIEMPRE responde en español. NUNCA uses inglés. "
    "REGLA CRÍTICA 1: El título y la descripción DEBEN referirse directamente al contenido específico "
    "del clip. Analiza qué se dice exactamente en la transcripción y crea metadata que refleje "
    "el tema concreto, no algo genérico. Si alguien dice algo sobre un error de marketing, el título "
    "debe mencionar el error, no solo decir 'esto cambia todo'."
    "REGLA CRÍTICA 2: BREVEDAD. Los títulos deben tener entre 30 y 60 caracteres "
    "(gancho + tema concreto, sin relleno). Las descripciones deben ser SINTÉTICAS y "
    "ORGANIZADAS por secciones en líneas separadas con emojis: "
    "máximo 2-3 oraciones cortas que resuman el punto clave + un call-to-action en su propia "
    "línea (con la palomita 👉) + la línea 'Video completo: <URL>' + los hashtags al final "
    "en su propia línea. TODO en menos de 350 caracteres totales. "
    "NUNCA copies frases completas de la transcripción; reformula para que se lea rápido "
    "en un teléfono. "
    "REGLA CRÍTICA 3: Incluye SIEMPRE al final de la descripción '▶️ Video completo: <URL>' "
    "si el video original tiene URL, y 6-10 hashtags relevantes de viralidad. " 
    "NUNCA repitas la transcripción tal cual. "
    "Respondes SOLO con JSON válido, sin texto adicional."
)

_TITLE_PATTERNS = [
    "{topic}",
    "Lo que nadie te cuenta sobre {topic}",
    "Esto cambia todo lo que sabías de {topic}",
    "La verdad que nadie dice sobre {topic}",
    "{topic} — la lección que nadie enseña",
    "No vas a creer lo que descubrí sobre {topic}",
    "El error más grande con {topic}",
    "Mira lo que pasó con {topic}",
    "{topic} 🔥 esto es lo que importa",
    "La razón por la que {topic} falla",
]

_CTA_OPTIONS = [
    "Suscríbete para más contenido como este 🔔",
    "Déjame tu opinión en los comentarios 👇",
    "Comparte si te sirvió 🔥",
    "Dale like si te identificas ❤️",
    "¿Tú qué opinas? Escríbeme abajo 💬",
    "Guarda este video para después 🔖",
]

GROQ_API_KEY = os.environ.get("EDGETAPE_GROQ_API_KEY")
GROQ_MODEL = os.environ.get("EDGETAPE_GROQ_MODEL", "gemma2-9b-it")
OLLAMA_URL = os.environ.get("EDGETAPE_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("EDGETAPE_OLLAMA_MODEL", "qwen2.5-coder:7b")


class MetadataGenerator(Protocol):
    name: str

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None
    ) -> dict: ...


class OllamaMetadataGenerator:
    """Genera metadata viral usando Ollama local (sin API key)."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or OLLAMA_MODEL
        self.base_url = (base_url or OLLAMA_URL).rstrip("/")

    @property
    def name(self) -> str:
        return f"ollama-metadata-{self.model}"

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None
    ) -> dict:
        prompt = _build_metadata_prompt(script, title_hint, duration, platform, source_url)
        content = self._complete(prompt)
        return _parse_metadata(content)

    def _complete(self, prompt: str) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VIRAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.7},
        }
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]


class GroqMetadataGenerator:
    """Genera metadata viral usando Groq API (gratis, sin tarjeta de crédito)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model or GROQ_MODEL
        self.api_key = api_key or GROQ_API_KEY
        self._client = client

    @property
    def name(self) -> str:
        return f"groq-metadata-{self.model}"

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None
    ) -> dict:
        prompt = _build_metadata_prompt(script, title_hint, duration, platform, source_url)
        content = self._complete(prompt)
        return _parse_metadata(content)

    def _complete(self, prompt: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VIRAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        client = self._client or httpx.Client(timeout=60.0)
        try:
            for attempt in range(5):
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    wait = (3 * (2 ** attempt)) + random.random() * 2
                    logger.warning("Groq 429 — retry %d in %.1fs", attempt + 1, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        finally:
            if self._client is None:
                client.close()


class LLMetadataGenerator:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model or os.environ.get("EDGETAPE_LLM_MODEL") or "gpt-4o-mini"
        self.base_url = (
            base_url or os.environ.get("EDGETAPE_LLM_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("EDGETAPE_LLM_API_KEY")
        self._client = client

    @property
    def name(self) -> str:
        return f"llm-metadata-{self.model}"

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None
    ) -> dict:
        prompt = _build_metadata_prompt(script, title_hint, duration, platform, source_url)
        content = self._complete(prompt)
        return _parse_metadata(content)

    def _complete(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": VIRAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        client = self._client or httpx.Client(timeout=60.0)
        try:
            for attempt in range(5):
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    wait = (3 * (2 ** attempt)) + random.random() * 2
                    logger.warning("LLM 429 — retry %d in %.1fs", attempt + 1, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        finally:
            if self._client is None:
                client.close()


class HeuristicMetadataGenerator:
    name = "heuristic-metadata"

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None
    ) -> dict:
        title = _heuristic_title(script, title_hint)
        description = _heuristic_description(script, duration, source_url)
        tags = _heuristic_tags(script, platform)
        return {"title": title, "description": description, "tags": tags}


def build_metadata_generator() -> MetadataGenerator:
    # 1. Groq API (gratis, sin tarjeta) — tiene prioridad si hay key
    if GROQ_API_KEY:
        return GroqMetadataGenerator()

    # 2. API remota (OpenAI, Groq legacy, etc.) — tiene prioridad si hay key
    if (
        os.environ.get("EDGETAPE_LLM_MODEL")
        or os.environ.get("EDGETAPE_LLM_API_KEY")
        or os.environ.get("EDGETAPE_LLM_BASE_URL")
    ):
        return LLMetadataGenerator()

    # 3. Ollama local (sin API key)
    try:
        with httpx.Client(timeout=3.0) as c:
            resp = c.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                if any(OLLAMA_MODEL in m for m in models):
                    return OllamaMetadataGenerator()
    except Exception:
        pass

    # 4. Fallback heurístico
    return HeuristicMetadataGenerator()


def generate_clip_metadata(
    generator: MetadataGenerator,
    clips: list[dict],
    platform: str = "youtube_shorts",
    source_url: str | None = None,
) -> list[dict]:
    for clip in clips:
        script = clip.get("script", "")
        if not script or len(script.strip()) < 10:
            logger.warning("clip has empty/short script (%d chars), using heuristic", len(script))
            clip["title"] = _heuristic_title(script, clip.get("title", ""))
            clip["description"] = _heuristic_description(script, clip.get("duration", 30.0), source_url)
            clip["tags"] = _heuristic_tags(script, platform)
            continue
        try:
            logger.info("generating metadata with %s for script=%d chars",
                        generator.name, len(script))
            logger.info("script preview: %s", script[:150])
            meta = generator.generate(
                script,
                clip.get("title", ""),
                clip.get("duration", 30.0),
                platform,
                source_url,
            )
            if not meta.get("title") and not meta.get("description"):
                raise ValueError("LLM returned empty metadata")
            clip["title"] = meta.get("title", clip.get("title", ""))
            clip["description"] = meta.get("description", "")
            clip["tags"] = meta.get("tags", [])
            logger.info("OK title=%s", clip["title"][:60])
        except Exception as exc:  # noqa: BLE001
            logger.warning("metadata generation FAILED (%s); using HEURISTIC", exc)
            clip["title"] = _heuristic_title(script, clip.get("title", ""))
            clip["description"] = _heuristic_description(script, clip.get("duration", 30.0), source_url)
            clip["tags"] = _heuristic_tags(script, platform)
            logger.info("heuristic title=%s", clip["title"][:60])
    return clips


def _build_metadata_prompt(script: str, title_hint: str, duration: float, platform: str, source_url: str | None = None) -> str:
    platform_names = {
        "youtube_shorts": "YouTube Shorts",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "facebook_reels": "Facebook Reels",
        "instagram_reels": "Instagram Reels",
    }
    pname = platform_names.get(platform, platform)
    max_title = 60 if "short" in platform or "tiktok" in platform or "reels" in platform else 100
    source_line = f"\nVideo original: {source_url}\n" if source_url else ""
    return (
        f"Plataforma objetivo: {pname}\n"
        f"Duración del clip: {duration:.0f} segundos{source_line}\n\n"
        f"Transcripción COMPLETA del clip:\n\"\"\"\n{script[:2500]}\n\"\"\"\n\n"
        f"Instrucciones (IMPORTANTE: responde SIEMPRE en español y sé BREVE):\n\n"
        f"1. TITLE ({30}-{max_title} caracteres):\n"
        f"   - Gancho emocional + tema concreto del clip, SIN relleno\n"
        f"   - Identifica el tema específico (ej: si habla de un error de pricing, menciona 'pricing')\n"
        f"   - Debe entenderse perfectamente en el título de un teléfono\n"
        f"   - NO uses títulos genéricos como 'Esto cambia todo' sin contexto\n"
        f"   - Ejemplos BUENOS: 'El error de pricing que le costó 10k al cliente', 'Nunca hagas esto en un Reel'\n"
        f"   - Ejemplos MALOS: 'No vas a creer lo que pasó' (demasiado genérico)\n\n"
        f"2. DESCRIPTION (máx 350 caracteres, estructura organizada en líneas separadas):\n"
        f"   - Línea 1: 🔥 + resumen SINTÉTICO y punchy del punto clave del clip (1-2 oraciones)\n"
        f"   - Línea 2 (opcional): 💡 + un detalle/insight extra concreto\n"
        f"   - Línea 3: 👉 + call-to-action corto (suscríbete, comenta, comparte)\n"
        f"   - Línea 4: ▶️ Video completo: {source_url or '[URL]'} (si hay video original)\n"
        f"   - Línea 5: hashtags (6-10, en minúsculas, incluye #shorts y 2-3 del tema)\n"
        f"   - Reformula, NUNCA copies frases completas de la transcripción\n"
        f"   - Máximo 2-3 emojis, usados como separadores de sección\n\n"
        f"3. TAGS (8-12 tags trending y relevantes, TODOS en minúsculas SIN '#'):\n"
        f"   - 3-5 tags específicos del tema (no solo genéricos como 'viral')\n"
        f"   - 2-3 tags de plataforma (#shorts #youtubeshorts #tiktok #reels)\n"
        f"   - 1-2 tags trending genéricos (#viral #trending #fyp)\n"
        f"   - Total: 8-12 tags, todos en minúsculas\n\n"
        f"Responde SOLO con JSON:\n"
        f'{{"title": "<título>", "description": "<descripción>", "tags": [<tags>]}}'
    )


def _parse_metadata(content: str) -> dict:
    cleaned = re.sub(r"```[\s\S]*?```", "", content).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("no JSON object found in LLM response")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return {
        "title": str(data.get("title", ""))[:100],
        "description": str(data.get("description", ""))[:2000],
        "tags": [str(t).lower().strip() for t in (data.get("tags") or [])][:15],
    }


def _heuristic_title(script: str, hint: str) -> str:
    words = _content_words(script)
    if not words:
        return "Momento clave"
    topic = " ".join(words[:8])
    pattern = random.choice(_TITLE_PATTERNS)
    title = pattern.format(topic=topic)
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0]
    return title


def _heuristic_description(script: str, duration: float, source_url: str | None = None) -> str:
    words = _content_words(script)
    if not words:
        base = f"Clip de {duration:.0f}s"
    else:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
        hook = sentences[0][:140] if sentences else " ".join(words[:12])
        idea = " ".join(words[1:9])
        cta = random.choice(_CTA_OPTIONS)
        base = (
            f"🔥 {hook}\n\n"
            f"💡 {idea} — detalle que marca la diferencia.\n\n"
            f"👉 {cta}"
        )
    if source_url:
        base += f"\n\n▶️ Video completo: {source_url}"
    topic_tag = words[0] if words else "contenido"
    base += f"\n\n#shorts #clip #viral #trending #{topic_tag}"
    return base


def _heuristic_tags(script: str, platform: str) -> list[str]:
    base = {"shorts", "clip", "viral", "trending", "fyp"}
    if "tiktok" in platform:
        base |= {"foryou", "foryoupage", "tiktokviral"}
    elif "reels" in platform:
        base |= {"reels", "instagram", "explore"}
    elif "youtube" in platform:
        base |= {"youtube", "youtubeshorts", "subscribe"}
    words = _content_words(script)
    for w in words[:5]:
        if len(w) > 3:
            base.add(w)
    return sorted(base)[:12]