from __future__ import annotations

import httpx
import pytest

from app.llm_scorer import (
    HeuristicSelector,
    LLMClipSelector,
    _best_segment,
    _build_prompt,
    _build_windows,
    _parse_response,
    _to_clips,
    build_clip_selector,
    select_clips_safely,
)


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


def _samples() -> list[dict]:
    return [
        _seg(0.0, 8.0, "Hablábamos del horario de la semana y de la logística de siempre."),
        _seg(9.0, 18.0, "La conclusión clave es que nuestro primer lanzamiento fracasó por completo y lo reconstruimos."),
        _seg(19.0, 27.0, "Luego pasamos a cómo reaccionó el cliente ante la nueva campaña."),
        _seg(100.0, 110.0, "El mejor consejo que recibimos fue empezar pensando en la audiencia."),
        _seg(112.0, 120.0, "Y después cerramos el programa con las despedidas de siempre."),
    ]


def test_windows_chunk_by_span() -> None:
    windows = _build_windows(_samples())
    assert len(windows) == 2
    assert windows[0]["start"] == 0.0
    assert windows[1]["start"] == 100.0
    assert len(windows[0]["segs"]) == 3
    assert len(windows[1]["segs"]) == 2


def test_prompt_mentions_windows_and_top_n() -> None:
    prompt = _build_prompt(_build_windows(_samples()), 120.0, 3)
    assert "W1 [" in prompt and "W2 [" in prompt
    assert "3 mejores momentos" in prompt
    assert '"window"' in prompt


def test_parse_response_handles_extra_text() -> None:
    content = 'Aquí tienes:\n[{"window": 2, "title": "El lanzamiento fallido", "quote": "empezar pensando en la audiencia", "reason": "específico y emocional"}]\nListo.'
    data = _parse_response(content)
    assert data[0]["window"] == 2


def test_parse_response_raises_without_array() -> None:
    with pytest.raises(ValueError):
        _parse_response("sin json aquí")


def test_best_segment_matches_quote() -> None:
    window = _build_windows(_samples())[0]
    best = _best_segment(window["segs"], "lanzamiento fracasó por completo")
    assert best["start"] == 9.0


def test_to_clips_maps_and_merges() -> None:
    windows = _build_windows(_samples())
    selections = [
        {"window": 2, "title": "Empieza con la audiencia", "quote": "empezar pensando en la audiencia", "reason": ""},
        {"window": 1, "title": "El lanzamiento fallido", "quote": "lanzamiento fracasó por completo", "reason": ""},
    ]
    clips = _to_clips(selections, windows, top_n=5)
    assert len(clips) == 2
    assert clips[0]["start"] < clips[1]["start"]
    for clip in clips:
        assert clip["title"]
        assert clip["line"]
        assert clip["duration"] >= 6.0
        assert clip["script"]


def test_to_clips_ignores_bad_windows() -> None:
    windows = _build_windows(_samples())
    clips = _to_clips([{"window": 99, "title": "x", "quote": "", "reason": ""}], windows, top_n=5)
    assert clips == []


def _mock_llm_client(selections: list[dict]) -> httpx.Client:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(selections)}}],
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_selector_end_to_end() -> None:
    client = _mock_llm_client([
        {"window": 1, "title": "El lanzamiento fallido", "quote": "lanzamiento fracasó por completo", "reason": ""},
    ])
    selector = LLMClipSelector(model="test-model", api_key="k", client=client)
    assert selector.name == "llm-test-model"

    clips = selector.select_clips(_samples(), 120.0, top_n=3)
    assert clips
    assert clips[0]["title"] == "El lanzamiento fallido"
    assert clips[0]["start"] >= 9.0


def test_llm_selector_sends_expected_request() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    selector = LLMClipSelector(model="m", base_url="https://example.com/v1", api_key="secret", client=client)
    selector.select_clips(_samples(), 120.0, top_n=2)

    assert captured["auth"] == "Bearer secret"
    assert '"model":"m"' in captured["body"]
    assert '"role":"system"' in captured["body"]


def test_select_clips_safely_falls_back_on_error() -> None:
    class Broken:
        name = "broken"

        def select_clips(self, segments, duration, top_n=10):
            raise RuntimeError("LLM down")

    clips = select_clips_safely(Broken(), _samples(), 120.0, top_n=3)
    assert clips  # heuristic fallback produced clips
    assert all(c["start"] < c["end"] for c in clips)


def test_heuristic_selector_matches_detect_clips() -> None:
    sel = HeuristicSelector()
    assert sel.name == "heuristic"
    assert sel.select_clips(_samples(), 120.0)


def test_build_clip_selector_defaults_to_heuristic(monkeypatch) -> None:
    for var in ("EDGETAPE_LLM_MODEL", "EDGETAPE_LLM_API_KEY", "EDGETAPE_LLM_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    selector = build_clip_selector()
    assert isinstance(selector, HeuristicSelector)


def test_build_clip_selector_uses_llm_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("EDGETAPE_LLM_MODEL", "my-model")
    selector = build_clip_selector()
    assert isinstance(selector, LLMClipSelector)
    assert selector.model == "my-model"
