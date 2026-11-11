from __future__ import annotations

import json

import pytest

from app import ai_generate as aig

_SCRIPT = {
    "title": "Boca Juniors",
    "hook": "El club que nació en el puerto",
    "script": (
        "Uno dos tres. Cuatro cinco seis. Siete ocho nueve. Diez once doce."
    ),
    "tags": ["boca", "futbol"],
    "queries": [
        "stadium crowd",
        "blue yellow flags",
        "players celebrating",
        "fans singing",
    ],
    "entities": ["Boca Juniors"],
    "visual_subject": "Boca Juniors",
}


def test_topic_plan_fallback_extracts_proper_noun() -> None:
    plan = aig._topic_plan_fallback("La historia de Boca Juniors")
    assert plan["visual_subject"] == "Boca Juniors"
    assert "Boca Juniors" in plan["entities"]


def test_topic_min_coverage_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EDGETAPE_TOPIC_MIN_COVERAGE", "0.6")
    assert aig._topic_min_coverage() == 0.6
    monkeypatch.setenv("EDGETAPE_TOPIC_MIN_COVERAGE", "no-es-numero")
    assert aig._topic_min_coverage() == 0.8


def test_write_script_uses_fact_sheet_and_reports_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EDGETAPE_TOPIC_PLAN", "1")
    monkeypatch.setenv("EDGETAPE_TOPIC_QA", "1")
    users: list[str] = []

    def _fake_complete(system: str, user: str, **kwargs) -> str:
        users.append(user)
        if "investigador" in system:
            return json.dumps({
                "entities": ["Boca Juniors"],
                "facts": ["Fundado en 1905"],
                "visual_subject": "Boca Juniors",
            })
        if "editor" in system:
            return json.dumps({"coverage": 0.9, "missing": [], "off_topic": []})
        return json.dumps(_SCRIPT)

    monkeypatch.setattr(aig, "_complete", _fake_complete)

    info = aig.write_script(
        "La historia de Boca Juniors", 15.0, "cinematic", "youtube_shorts"
    )

    assert info["entities"] == ["Boca Juniors"]
    assert info["visual_subject"] == "Boca Juniors"
    assert info["facts"] == ["Fundado en 1905"]
    assert info["topic_coverage"] == 0.9
    assert len(info["shots"]) == len(info["sentences"])
    assert info["shots"][0]["shot_type"] == "hook"
    assert info["shots"][-1]["shot_type"] == "cta"
    assert any("Entidades del tema: Boca Juniors" in u for u in users)
    assert any("Hechos verificados" in u for u in users)


def test_write_script_warns_on_low_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EDGETAPE_TOPIC_PLAN", "0")
    monkeypatch.setenv("EDGETAPE_TOPIC_QA", "1")

    def _fake_complete(system: str, user: str, **kwargs) -> str:
        if "editor" in system:
            return json.dumps({"coverage": 0.4, "missing": ["Boca Juniors"], "off_topic": []})
        return json.dumps(_SCRIPT)

    monkeypatch.setattr(aig, "_complete", _fake_complete)

    info = aig.write_script(
        "La historia de Boca Juniors", 360.0, "cinematic", "youtube"
    )

    assert info["topic_coverage"] == 0.4
    assert any("cobertura del tema baja" in w for w in info["warnings"])
