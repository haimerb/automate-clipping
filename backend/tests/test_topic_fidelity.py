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


def test_anchor_queries_prefixes_generic_queries() -> None:
    anchored = aig._anchor_queries(
        ["stadium crowd", "Boca Juniors fans", "", "trophy victory"],
        "Boca Juniors",
    )
    assert anchored == [
        "Boca Juniors stadium crowd",
        "Boca Juniors fans",
        "",
        "Boca Juniors trophy victory",
    ]


def test_candidate_images_accepts_landscape_but_prefers_portrait() -> None:
    pages = {
        "1": {"imageinfo": [{
            "mime": "image/jpeg", "width": 1600, "height": 900,
            "thumburl": "https://x/landscape.jpg",
        }]},
        "2": {"imageinfo": [{
            "mime": "image/jpeg", "width": 900, "height": 1600,
            "thumburl": "https://x/portrait.jpg",
        }]},
    }
    urls = aig._candidate_images(pages, want_landscape=False)
    assert urls == ["https://x/portrait.jpg", "https://x/landscape.jpg"]


def test_wiki_json_retries_transient_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aig.time, "sleep", lambda *_: None)

    class _Resp:
        def __init__(self, status: int, data: dict) -> None:
            self.status_code = status
            self._data = data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> dict:
            return self._data

    class _Client:
        calls = 0

        def get(self, url: str, params: dict):
            self.calls += 1
            if self.calls < 3:
                return _Resp(403, {})
            return _Resp(200, {"ok": 1})

    client = _Client()
    assert aig._wiki_json(client, "commons.wikimedia.org", {}) == {"ok": 1}
    assert client.calls == 3


def test_topic_images_use_landscape_when_vertical(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_TOPIC_IMAGES", "1")

    def _fake_wiki(client, host, params, retries=3):
        return {"query": {"pages": {"1": {"imageinfo": [{
            "mime": "image/jpeg", "width": 1600, "height": 900,
            "thumburl": "https://x/landscape.jpg",
        }]}}}}

    class _Resp:
        status_code = 200
        content = b"x" * 2048
        headers = {"content-type": "image/jpeg"}

    class _Client:
        def get(self, url, timeout=None):
            return _Resp()

    monkeypatch.setattr(aig, "_wiki_json", _fake_wiki)
    images = aig._fetch_wikimedia_topic_images(
        "Boca Juniors", 1, (1080, 1920), tmp_path, client=_Client(),
    )
    assert len(images) == 1
    assert images[0].read_bytes() == b"x" * 2048
