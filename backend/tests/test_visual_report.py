from __future__ import annotations

from pathlib import Path

import pytest

from app import ai_generate as aig


def test_fetch_scene_media_reports_topic_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    monkeypatch.setattr(aig.materials, "build_library", lambda: None)
    monkeypatch.setattr(aig.ai_images, "is_configured", lambda: False)
    monkeypatch.setattr(aig.ai_video, "is_configured", lambda: False)
    monkeypatch.setattr(aig, "_try_videogen", lambda pending, *a, **k: pending)
    monkeypatch.setattr(aig, "_fetch_wikimedia_images", lambda *a, **k: [None, None, None, None])

    topic_still = tmp_path / "boca.jpg"
    topic_still.write_bytes(b"jpg")
    monkeypatch.setattr(
        aig, "_fetch_wikimedia_topic_images", lambda *a, **k: [topic_still, topic_still]
    )

    report: dict = {}
    assets = aig._fetch_scene_media(
        ["a.", "b.", "c.", "d."],
        ["stadium", "flags", "fans", "goal"],
        (1080, 1920),
        tmp_path,
        topic="Boca Juniors",
        report=report,
    )

    assert assets[1][0] == topic_still and assets[1][1] is False
    assert assets[2][0] == topic_still
    assert assets[0][0] is None and assets[3][0] is None
    assert report["topic"] == "Boca Juniors"
    assert report["providers"] == {"wikimedia-topic": 2}
    assert report["scenes"][1]["provider"] == "wikimedia-topic"
    assert report["scenes"][1]["kind"] == "image"
    assert report["scenes"][0]["provider"] == "brand"
    assert report["scenes"][0]["kind"] == "gradient"


def test_fetch_scene_media_marks_ai_image_and_hero_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    monkeypatch.setenv("EDGETAPE_HERO_SHOTS", "1")
    monkeypatch.setattr(aig.materials, "build_library", lambda: None)
    monkeypatch.setattr(aig.ai_images, "is_configured", lambda: True)
    monkeypatch.setattr(aig.ai_video, "is_configured", lambda: True)
    monkeypatch.setattr(aig, "_try_videogen", lambda pending, *a, **k: pending)
    monkeypatch.setattr(aig, "_fetch_wikimedia_images", lambda *a, **k: [None, None, None])

    def _gen_image(prompt: str, size, out: Path):
        out = out.with_suffix(".png")
        out.write_bytes(b"ai")
        return out

    def _gen_video(image: Path, prompt: str, out: Path):
        out.write_bytes(b"hero")
        return out

    monkeypatch.setattr(aig.ai_images, "generate_image", _gen_image)
    monkeypatch.setattr(aig.ai_video, "image_to_video", _gen_video)

    report: dict = {}
    assets = aig._fetch_scene_media(
        ["a.", "b.", "c."], ["one", "two", "three"], (1080, 1920), tmp_path, report=report
    )

    assert assets[1][1] is True
    assert assets[1][0].name == "scene_1.hero.mp4"
    assert report["providers"] == {"cloudflare-flux": 1, "hf-zerogpu": 1}
    assert report["scenes"][1]["provider"] == "hf-zerogpu"
    assert report["scenes"][1]["kind"] == "video"


def test_fetch_scene_media_without_topic_leaves_brand_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    monkeypatch.setattr(aig.materials, "build_library", lambda: None)
    monkeypatch.setattr(aig.ai_images, "is_configured", lambda: False)
    monkeypatch.setattr(aig.ai_video, "is_configured", lambda: False)
    monkeypatch.setattr(aig, "_try_videogen", lambda pending, *a, **k: pending)
    monkeypatch.setattr(aig, "_fetch_wikimedia_images", lambda *a, **k: [None, None, None])

    report: dict = {}
    assets = aig._fetch_scene_media(
        ["a.", "b.", "c."], None, (1920, 1080), tmp_path, report=report
    )

    assert assets == [(None, False)] * 3
    assert report["topic"] == ""
    assert report["providers"] == {}
    assert [s["kind"] for s in report["scenes"]] == ["gradient"] * 3
