from __future__ import annotations

import json
import logging
import os
import re
from typing import Protocol

import httpx

from .scorer import TOP_N, _TOKEN_RE, _limits_for, detect_clips

logger = logging.getLogger(__name__)

WINDOW_SEC = 90.0
MAX_WINDOWS = 30
MAX_TEXT = 900

SYSTEM_PROMPT = (
    "Eres el selector de clips de una herramienta de recorte de audio y video. "
    "Dada una ventana de transcripción de una grabación larga, elige los momentos "
    "que funcionarían mejor como clips independientes: pasajes específicos, "
    "emocionales, sorprendentes o instructivos. Nunca elijas conversación trivial, "
    "logística o saludos."
)


class ClipSelector(Protocol):
    name: str

    def select_clips(
        self, segments: list[dict], duration: float, top_n: int = TOP_N,
        platform: str | None = None,
    ) -> list[dict]: ...


class HeuristicSelector:
    name = "heuristic"

    def select_clips(
        self, segments: list[dict], duration: float, top_n: int = TOP_N,
        platform: str | None = None,
    ) -> list[dict]:
        return detect_clips(segments, top_n, platform)


class LLMClipSelector:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.model = model or os.environ.get("EDGETAPE_LLM_MODEL") or "gpt-4o-mini"
        self.base_url = (base_url or os.environ.get("EDGETAPE_LLM_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("EDGETAPE_LLM_API_KEY")
        self._client = client

    @property
    def name(self) -> str:
        return f"llm-{self.model}"

    def select_clips(
        self, segments: list[dict], duration: float, top_n: int = TOP_N,
        platform: str | None = None,
    ) -> list[dict]:
        windows = _build_windows(segments)
        if not windows:
            return []
        prompt = _build_prompt(windows, duration, top_n)
        content = self._complete(prompt)
        selections = _parse_response(content)
        return _to_clips(selections, windows, top_n, platform)

    def _complete(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        client = self._client or httpx.Client(timeout=60.0)
        try:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        finally:
            if self._client is None:
                client.close()


def select_clips_safely(
    selector: ClipSelector, segments: list[dict], duration: float,
    top_n: int = TOP_N, platform: str | None = None,
) -> list[dict]:
    try:
        return selector.select_clips(segments, duration, top_n, platform)
    except Exception as exc:  # noqa: BLE001
        logger.warning("selector %s failed (%s); using heuristic", selector.name, exc)
        return detect_clips(segments, top_n, platform)


def build_clip_selector() -> ClipSelector:
    if (os.environ.get("EDGETAPE_LLM_MODEL")
            or os.environ.get("EDGETAPE_LLM_API_KEY")
            or os.environ.get("EDGETAPE_LLM_BASE_URL")):
        return LLMClipSelector()
    return HeuristicSelector()


def _build_windows(segments: list[dict], window_sec: float = WINDOW_SEC) -> list[dict]:
    windows: list[dict] = []
    for seg in segments:
        if not windows or seg["start"] - windows[-1]["start"] >= window_sec:
            windows.append({"start": seg["start"], "end": seg["end"], "segs": []})
        current = windows[-1]
        current["end"] = max(current["end"], seg["end"])
        current["segs"].append(seg)
    return windows


def _fmt_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_windows(windows: list[dict]) -> str:
    lines = []
    for i, w in enumerate(windows[:MAX_WINDOWS], 1):
        text = " ".join(s["text"] for s in w["segs"])
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "…"
        lines.append(f"W{i} [{_fmt_ts(w['start'])} - {_fmt_ts(w['end'])}]: {text}")
    return "\n".join(lines)


def _build_prompt(windows: list[dict], duration: float, top_n: int) -> str:
    return (
        f"Duración de la grabación: {_fmt_ts(duration)}.\n"
        f"Ventanas de transcripción:\n{_fmt_windows(windows)}\n\n"
        f"Elige los {top_n} mejores momentos para cortar como clips independientes.\n"
        "Devuelve SOLO un arreglo JSON de objetos, cada uno con los campos:\n"
        '{"window": <número de ventana 1-based>, "title": "<título corto y llamativo>", '
        '"quote": "<cita corta y exacta de esa ventana>", "reason": "<una línea>"}'
    )


def _parse_response(content: str) -> list[dict]:
    match = re.search(r"\[[\s\S]*\]", content)
    if not match:
        raise ValueError("no JSON array found in LLM response")
    data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("LLM response is not a JSON array")
    return data


def _best_segment(segs: list[dict], quote: str) -> dict:
    if not quote:
        return segs[0]
    quote_words = set(_TOKEN_RE.findall(quote.lower()))
    if not quote_words:
        return segs[0]

    def overlap(seg: dict) -> int:
        return len(quote_words & set(_TOKEN_RE.findall(seg["text"].lower())))

    return max(segs, key=overlap)


def _to_clips(selections: list[dict], windows: list[dict], top_n: int,
              platform: str | None = None) -> list[dict]:
    _, MAX_LEN = _limits_for(platform)
    clips: list[dict] = []
    for sel in selections:
        if not isinstance(sel, dict):
            continue
        idx = sel.get("window")
        if not isinstance(idx, int) or not (1 <= idx <= len(windows)):
            continue
        window = windows[idx - 1]
        quote = str(sel.get("quote") or "").strip()
        title = str(sel.get("title") or "").strip() or "Momento clave"

        seg = _best_segment(window["segs"], quote)
        start = seg["start"]
        end = min(seg["end"] + 15.0, window["end"])
        for nxt in window["segs"]:
            if nxt["start"] <= seg["end"]:
                continue
            if nxt["start"] >= end:
                break
            end = min(end, max(end, nxt["end"]))
        if end - start < 8.0:
            for nxt in window["segs"]:
                if nxt["start"] > seg["end"] and nxt["end"] <= window["end"]:
                    end = min(end + (nxt["end"] - nxt["start"]), window["end"])
                    if end - start >= 8.0:
                        break
        if end - start < 6.0:
            continue
        end = min(end, start + MAX_LEN)
        script = " ".join(
            s["text"] for s in window["segs"]
            if s["start"] >= start - 0.5 and s["end"] <= end + 0.5
        )
        clips.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "title": title,
            "line": quote or script[:120],
            "script": script,
            "score": 1.0,
        })

    clips.sort(key=lambda c: c["start"])
    merged: list[dict] = []
    for clip in clips:
        if merged and clip["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], clip["end"])
            merged[-1]["duration"] = round(merged[-1]["end"] - merged[-1]["start"], 3)
            continue
        merged.append(clip)
    return merged[:top_n]
