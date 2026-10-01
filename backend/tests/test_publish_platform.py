"""La plataforma del job manda en el export y en la publicación.

Regresión del bug reportado: un video generado como "YouTube (video)" de 6 min
(horizontal, hasta 900s) se publicaba como Short (vertical, hasta 60s). El
recorte pasaba en dos sitios y los dos eran silenciosos:

1. El paso de publicar no leía la plataforma del job; el frontend ofrecía
   `youtube_shorts` por defecto en el selector de destino.
2. `export_clip` reutilizaba cualquier export previo solo comparando duración
   (`60 <= 900`), así que el mp4 vertical de 60s se subía tal cual a YouTube.
"""

import asyncio
import json

import pytest

from app import publish
from app.models import Clip, Job
from app.processing import _export_mode_for, export_clip
from app.scorer import _limits_for
from app.storage import JobStore


def _store(tmp_path) -> JobStore:
    store = JobStore(tmp_path)
    store.job_dir("j1").mkdir(parents=True, exist_ok=True)
    job = Job(
        id="j1",
        filename="src.mp4",
        status="done",
        duration=360.0,
        platform="youtube",
        created_at="2026-01-01T00:00:00",
    )
    store.save_job(job)
    return store


@pytest.fixture(autouse=True)
def _no_export_mode_override(monkeypatch: pytest.MonkeyPatch):
    """conftest fija EDGETAPE_EXPORT_MODE=original para acelerar los renders;
    estos tests necesitan el default real de la función."""
    monkeypatch.delenv("EDGETAPE_EXPORT_MODE", raising=False)


def _add_clip(store: JobStore, duration: float = 360.0, **kw) -> Clip:
    clip = Clip(
        id="c1",
        index=1,
        start=0.0,
        end=duration,
        duration=duration,
        title="El tema",
        line="frase",
        script="frase",
        score=1.0,
        **kw,
    )
    store.save_clips("j1", [clip])
    return clip


def _export(store: JobStore, platform: str, max_duration: float):
    return asyncio.run(
        export_clip("j1", "c1", store, max_duration=max_duration, platform=platform)
    )


class TestFormatLimits:
    def test_youtube_allows_long_form(self) -> None:
        assert _limits_for("youtube")[1] >= 360.0

    def test_shorts_caps_at_one_minute(self) -> None:
        assert _limits_for("youtube_shorts")[1] == 60.0

    def test_the_regression_gap_is_real(self) -> None:
        """6 min entra en YouTube video y NO en Shorts: ese es el bug."""
        assert 360.0 <= _limits_for("youtube")[1]
        assert 360.0 > _limits_for("youtube_shorts")[1]


class TestExportModePerPlatform:
    def test_horizontal_is_not_blurred(self) -> None:
        """Un video horizontal de YouTube no puede salir con fondo borroso."""
        job = Job(id="j", filename="f", platform="youtube",
                  created_at="2026-01-01T00:00:00")
        assert _export_mode_for(job, "youtube") == "original"

    def test_vertical_formats_blur(self) -> None:
        job = Job(id="j", filename="f", platform="youtube_shorts",
                  created_at="2026-01-01T00:00:00")
        assert _export_mode_for(job, "youtube_shorts") == "vertical_blur"
        assert _export_mode_for(job, "tiktok") == "vertical_blur"

    def test_env_override_still_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_EXPORT_MODE", "vertical_crop")
        job = Job(id="j", filename="f", platform="youtube",
                  created_at="2026-01-01T00:00:00")
        assert _export_mode_for(job, "youtube") == "vertical_crop"

    def test_conftest_override_is_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El override de env manda siempre, para no romper la suite."""
        monkeypatch.setenv("EDGETAPE_EXPORT_MODE", "original")
        job = Job(id="j", filename="f", platform="tiktok",
                  created_at="2026-01-01T00:00:00")
        assert _export_mode_for(job, "tiktok") == "original"


class TestPlatformIsRecorded:
    def test_job_has_platform_field(self) -> None:
        """Sin `Job.platform`, el paso de publicar no tiene nada que leer."""
        job = Job(id="j", filename="f", platform="youtube",
                  created_at="2026-01-01T00:00:00")
        assert job.platform == "youtube"

    def test_defaults_to_shorts_for_legacy_jobs(self) -> None:
        """Jobs viejos sin el campo no rompen: asumen el default de siempre."""
        job = Job(id="j", filename="f", created_at="2026-01-01T00:00:00")
        assert job.platform == "youtube_shorts"

    def test_platform_survives_serialization(self, tmp_path) -> None:
        store = _store(tmp_path)
        loaded = store.get_job("j1")
        assert loaded is not None
        assert loaded.platform == "youtube"
        raw = json.loads((tmp_path / "j1" / "job.json").read_text(encoding="utf-8"))
        assert raw["platform"] == "youtube"

    def test_clip_records_export_platform(self) -> None:
        clip = Clip(id="c", index=1, start=0.0, end=10.0, duration=10.0,
                    title="t", line="l", script="s", score=1.0)
        assert clip.export_platform is None


class TestExportReuseRespectsPlatform:
    def test_reexports_when_platform_changes(self, tmp_path, monkeypatch) -> None:
        """El bug clave: export de Shorts (60s) reutilizado para YouTube.

        Antes `export_clip` comparaba solo la duración (`60 <= 900`) y devolvía
        el mp4 vertical de 60s. Ahora la plataforma del export anterior manda.
        """
        store = _store(tmp_path)
        _add_clip(store, duration=360.0)
        cuts: list[dict] = []

        def _fake_cut(source, start, end, out, mode, caption=None):
            cuts.append({"start": start, "end": end, "mode": mode})
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 1024)

        monkeypatch.setattr("app.processing.cut_clip", _fake_cut)

        clip = _export(store, platform="youtube_shorts", max_duration=60.0)
        assert clip is not None and clip.export_platform == "youtube_shorts"
        assert cuts[-1]["end"] == pytest.approx(60.0)
        assert cuts[-1]["mode"] == "vertical_blur"

        clip2 = _export(store, platform="youtube", max_duration=900.0)
        assert clip2 is not None
        assert len(cuts) == 2, "no debe reutilizar un export de otra plataforma"
        assert cuts[-1]["end"] == pytest.approx(360.0)
        assert cuts[-1]["mode"] == "original", "horizontal no lleva blur"
        assert clip2.export_platform == "youtube"

    def test_same_platform_reuses_when_short_enough(
        self, tmp_path, monkeypatch
    ) -> None:
        """Misma plataforma y duración ya dentro del límite: no se re-corta."""
        store = _store(tmp_path)
        _add_clip(store, duration=45.0)
        calls: list[float] = []

        def _fake_cut(source, start, end, out, mode, caption=None):
            calls.append(end)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\x00" * 1024)

        monkeypatch.setattr("app.processing.cut_clip", _fake_cut)
        # el 1º export escribe un archivo que ffprobe no puede medir; el reuso
        # necesita duración conocida, así que se parte de un clip ya exportado
        clip = store.get_clips("j1")[0]
        clip.exported = True
        clip.export_name = "c1_ya.mp4"
        clip.export_platform = "youtube_shorts"
        store.save_clips("j1", [clip])
        out = store.exports_dir("j1") / "c1_ya.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 1024)

        monkeypatch.setattr(
            "app.processing.probe_duration", lambda p: 45.0
        )
        result = _export(store, platform="youtube_shorts", max_duration=60.0)
        assert result is not None
        assert calls == [], "no debe re-cortar si ya cumple"
        assert result.export_platform == "youtube_shorts"


class TestPublishPassesPlatform:
    def test_publish_one_forwards_platform_to_export(
        self, tmp_path, monkeypatch
    ) -> None:
        """`publish_one` debe pasar la plataforma del destino al export."""
        seen: dict = {}

        async def _fake_export(job_id, clip_id, store, max_duration=None, platform=None):
            seen["max_duration"] = max_duration
            seen["platform"] = platform
            return None

        monkeypatch.setattr(publish, "export_clip", _fake_export)
        store = _store(tmp_path)
        _add_clip(store, duration=360.0)
        job = store.get_job("j1")
        assert job is not None

        asyncio.run(
            publish.publish_one(store, job, store.get_clips("j1")[0], "youtube", "canal")
        )
        assert seen["platform"] == "youtube"
        assert seen["max_duration"] == _limits_for("youtube")[1]

    def test_shorts_still_truncates_to_60s(self, tmp_path, monkeypatch) -> None:
        """Shorts sigue recortando a 60s: el fix no toca ese caso."""
        seen: dict = {}

        async def _fake_export(job_id, clip_id, store, max_duration=None, platform=None):
            seen.update(max_duration=max_duration, platform=platform)
            return None

        monkeypatch.setattr(publish, "export_clip", _fake_export)
        store = _store(tmp_path)
        _add_clip(store, duration=360.0)
        job = store.get_job("j1")
        assert job is not None

        asyncio.run(
            publish.publish_one(
                store, job, store.get_clips("j1")[0], "youtube_shorts", "canal"
            )
        )
        assert seen["platform"] == "youtube_shorts"
        assert seen["max_duration"] == 60.0
