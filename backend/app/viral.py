from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Protocol

import httpx

from .scorer import _content_words

logger = logging.getLogger(__name__)

VIRAL_SYSTEM = (
    "Eres un experto en marketing de contenido viral para YouTube, TikTok y redes sociales. "
    "Generas títulos, descripciones y tags que maximizan views, engagement y shares. "
    "La descripción debe ser ORIGINAL: analiza el contenido del clip y escribe una descripción "
    "que resuma de qué trata el video, destaque el momento clave, incluya un call-to-action "
    "y emojis relevantes. NUNCA repitas la transcripción tal cual. "
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


class MetadataGenerator(Protocol):
    name: str

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str
    ) -> dict: ...


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
        self, script: str, title_hint: str, duration: float, platform: str
    ) -> dict:
        prompt = _build_metadata_prompt(script, title_hint, duration, platform)
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
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        finally:
            if self._client is None:
                client.close()


class HeuristicMetadataGenerator:
    name = "heuristic-metadata"

    def generate(
        self, script: str, title_hint: str, duration: float, platform: str
    ) -> dict:
        title = _heuristic_title(script, title_hint)
        description = _heuristic_description(script, duration)
        tags = _heuristic_tags(script, platform)
        return {"title": title, "description": description, "tags": tags}


def build_metadata_generator() -> MetadataGenerator:
    if (
        os.environ.get("EDGETAPE_LLM_MODEL")
        or os.environ.get("EDGETAPE_LLM_API_KEY")
        or os.environ.get("EDGETAPE_LLM_BASE_URL")
    ):
        return LLMetadataGenerator()
    return HeuristicMetadataGenerator()


def generate_clip_metadata(
    generator: MetadataGenerator,
    clips: list[dict],
    platform: str = "youtube_shorts",
) -> list[dict]:
    for clip in clips:
        try:
            meta = generator.generate(
                clip.get("script", ""),
                clip.get("title", ""),
                clip.get("duration", 30.0),
                platform,
            )
            clip["title"] = meta.get("title", clip.get("title", ""))
            clip["description"] = meta.get("description", "")
            clip["tags"] = meta.get("tags", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("metadata generation failed for clip (%s)", exc)
            clip["description"] = clip.get("script", "")[:300]
            clip["tags"] = _heuristic_tags(clip.get("script", ""), platform)
    return clips


def _build_metadata_prompt(script: str, title_hint: str, duration: float, platform: str) -> str:
    platform_names = {
        "youtube_shorts": "YouTube Shorts",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "facebook_reels": "Facebook Reels",
        "instagram_reels": "Instagram Reels",
    }
    pname = platform_names.get(platform, platform)
    max_title = 60 if "short" in platform or "tiktok" in platform or "reels" in platform else 100
    return (
        f"Plataforma objetivo: {pname}\n"
        f"Duración del clip: {duration:.0f} segundos\n"
        f"Sugerencia de título: {title_hint}\n\n"
        f"Transcripción del clip:\n{script[:2000]}\n\n"
        f"Instrucciones:\n"
        f"1. TITLE: Título gancho optimizado para {pname}, máx {max_title} caracteres. "
        f"Usa ganchos emocionales, números, preguntas o promesas de valor.\n"
        f"2. DESCRIPTION: Descripción ORIGINAL de 2-3 oraciones que resuma de qué trata "
        f"el video, destaque el momento clave o la enseñanza, incluya un call-to-action "
        f"(suscríbete, comenta, comparte) y 2-3 emojis. NO repitas la transcripción.\n"
        f"3. TAGS: 8-12 tags trending y relevantes en minúsculas.\n\n"
        f"Responde SOLO con JSON:\n"
        f'{{"title": "<título>", "description": "<descripción>", "tags": [<tags>]}}'
    )


def _parse_metadata(content: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", content)
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
    topic = " ".join(words[:5])
    pattern = random.choice(_TITLE_PATTERNS)
    title = pattern.format(topic=topic)
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0]
    return title


def _heuristic_description(script: str, duration: float) -> str:
    words = _content_words(script)
    if not words:
        return f"Clip de {duration:.0f}s #shorts #clip #viral"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    hook = sentences[0][:150] if sentences else " ".join(words[:12])
    cta = random.choice(_CTA_OPTIONS)
    return (
        f"🔥 {hook}\n\n"
        f"Momento clave de {duration:.0f}s que no te puedes perder.\n"
        f"{cta}\n\n"
        f"#shorts #clip #viral #trending"
    )


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
