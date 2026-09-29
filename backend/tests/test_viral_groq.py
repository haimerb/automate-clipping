"""Metadatos virales de Groq: default vigente y rotación de modelo dado de baja.

Groq decomisionó `gemma2-9b-it` (400 `model_decommissioned`) y con él se cayó la
generación de títulos/descripciones al heurístico. Estos tests fijan el default
actual y la rotación al siguiente modelo de la cadena.
"""

import json

import httpx
import pytest

from app import viral

_ANSWER = json.dumps(
    {
        "title": "Espresso en casa: el truco del chorro miel",
        "description": "🔥 Saca un espresso perfecto con molienda fina.",
        "tags": ["espresso", "molienda", "fyp"],
    },
    ensure_ascii=False,
)


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _decommissioned(model: str) -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": f"The model `{model}` has been decommissioned and is no longer supported.",
                "code": "model_decommissioned",
            }
        },
    )


def test_default_model_no_es_el_retirado() -> None:
    assert viral.GROQ_MODEL == "openai/gpt-oss-20b"
    assert "gemma2-9b-it" not in (viral.GROQ_MODEL, *viral.GROQ_FALLBACK_MODELS)
    assert viral.GROQ_FALLBACK_MODELS


def test_rota_al_siguiente_modelo_cuando_el_default_fue_retirado() -> None:
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        pedidos.append(model)
        if model == viral.GROQ_MODEL:
            return _decommissioned(model)
        return _ok(_ANSWER)

    gen = viral.GroqMetadataGenerator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    meta = gen.generate("guion de espresso", "", 18.0, "tiktok")

    assert pedidos[:2] == [viral.GROQ_MODEL, viral.GROQ_FALLBACK_MODELS[0]]
    assert meta["title"].startswith("Espresso en casa")
    assert meta["tags"][0] == "espresso"


def test_no_reintenta_un_400_y_avanza_rapido() -> None:
    """Un 400 por modelo retirado no debe gastar los 5 reintentos con backoff."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _decommissioned(json.loads(request.content)["model"])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gen = viral.GroqMetadataGenerator(api_key="k", client=client)
    with pytest.raises(httpx.HTTPStatusError):
        gen.generate("guion", "", 18.0, "tiktok")

    assert calls == 1 + len(viral.GROQ_FALLBACK_MODELS)


def test_usa_el_modelo_configurado_por_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(viral, "GROQ_MODEL", "qwen/qwen3.8-27b")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["model"])
        return _ok(_ANSWER)

    gen = viral.GroqMetadataGenerator(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    gen.generate("guion", "", 18.0, "tiktok")
    assert seen == ["qwen/qwen3.8-27b"]
