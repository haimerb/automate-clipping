"""Hashtags: relevantes y limitados, con enriquecimiento opcional por tendencia.

El bug que motivó esto: todos los videos salían con los mismos ~12 tags
(`viral`, `trending`, `fyp` + 5 palabras del texto). That's hashtag stuffing:
diluye el alcance y el algoritmo prioriza retención, no cantidad de tags.

Estos tests fijan tres cosas:
1. `_heuristic_tags` devuelve 3-6 tags con especificidad del tema.
2. `_finalize_tags` topa a 6 aunque el LLM devuelva 15.
3. `trends` nunca rompe la metadata si no hay red.
"""

import json

import httpx
import pytest

from app import trends, viral


class TestHeuristicTags:
    def test_returns_few_relevant_tags(self) -> None:
        """3-6 tags, no 12, y con palabras del tema."""
        script = (
            "El error de pricing que le costo caro al cliente fue no medir "
            "laConversion antes de subir las ventas del trimestre."
        )
        tags = viral._heuristic_tags(script, "youtube_shorts")

        assert 3 <= len(tags) <= 6, tags
        # debe aparecer al menos una palabra específica del tema
        assert any(t in script.lower() for t in tags), tags

    def test_not_the_same_generic_bag(self) -> None:
        """Dos temas muy distintos no pueden colapsar al mismo set de tags."""
        a = viral._heuristic_tags(
            "El error de pricing que le custo caro al cliente",
            "youtube_shorts",
        )
        b = viral._heuristic_tags(
            "Mi gata maula toda la noche y no entiendo por que",
            "youtube_shorts",
        )
        assert a != b, (a, b)

    def test_drops_stopwords(self) -> None:
        """`porque`, `este`, `pero`... no sirven como hashtags."""
        script = "porque este pero cuando donde porque este pero cuando donde"
        tags = viral._heuristic_tags(script, "tiktok")
        for junk in ("porque", "este", "pero", "cuando", "donde"):
            assert junk not in tags, tags

    def test_platform_tag_present(self) -> None:
        assert "tiktok" in viral._heuristic_tags("un tema sobre cafe", "tiktok")
        assert "reels" in viral._heuristic_tags("un tema sobre cafe", "instagram_reels")


class TestFinalizeTags:
    def test_caps_at_six(self) -> None:
        """Aunque el LLM devuelva 15 tags, se topa a 6."""
        many = [f"tag{i}" for i in range(15)]
        out = viral._finalize_tags(many, "un guion sobre pricing", "youtube_shorts")
        assert len(out) <= viral.MAX_TAGS, out

    def test_strips_hash_and_spaces(self) -> None:
        out = viral._finalize_tags(
            ["#pricing", "  Ventas  ", "conversion", "shorts", "viral"],
            "guion sobre pricing",
            "youtube_shorts",
        )
        assert "pricing" in out
        assert "ventas" in out
        assert all(" " not in t for t in out), out

    def test_empty_tags_falls_back_to_heuristic(self) -> None:
        """Sin tags del LLM se generan, no se devuelve una lista vacía."""
        out = viral._finalize_tags([], "hablo de marketing de email", "youtube_shorts")
        assert out, "tags vacíos = clip sin descubrimiento"
        assert len(out) <= viral.MAX_TAGS

    def test_never_raises_when_trends_die(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sin red, los tags del LLM se conservan intactos."""
        monkeypatch.setenv("EDGETAPE_TRENDS", "1")

        def _boom() -> list[str]:
            raise RuntimeError("sin red")

        monkeypatch.setattr(trends, "get_trending_hashtags", _boom)
        out = viral._finalize_tags(["pricing", "ventas", "shorts"], "guion", "youtube_shorts")
        assert out == ["pricing", "ventas", "shorts"], out


class TestTrendsDisabled:
    def test_off_returns_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_TRENDS", "0")
        assert trends.get_trending_hashtags("youtube_shorts") == []

    def test_no_network_in_tests_by_default(self) -> None:
        """conftest apaga las tendencias: la suite no debe hacer red."""
        assert trends.get_trending_hashtags("tiktok") == []


class TestTrendsCache:
    def test_cached_tags_skip_network(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EDGETAPE_STORAGE", str(tmp_path))
        monkeypatch.delenv("EDGETAPE_TRENDS", raising=False)

        # precarga la cache a mano
        trends._write_cache("tiktok", ["cafecito", "matcha"])

        called = {"n": 0}

        def _fail() -> list[str]:
            called["n"] += 1
            raise AssertionError("no debe consultar la red si hay cache")

        monkeypatch.setattr(trends, "_tiktok_trends", _fail)
        assert trends.get_trending_hashtags("tiktok") == ["cafecito", "matcha"]
        assert called["n"] == 0

    def test_expired_cache_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EDGETAPE_STORAGE", str(tmp_path))
        monkeypatch.setenv("EDGETAPE_TRENDS_TTL", "300")
        monkeypatch.delenv("EDGETAPE_TRENDS", raising=False)

        trends._write_cache("tiktok", ["viejo"])
        # envejecemos el archivo más allá del TTL
        path = trends._cache_path("tiktok")
        import os
        import time

        os.utime(path, (time.time() - 3600, time.time() - 3600))

        monkeypatch.setattr(trends, "_tiktok_trends", lambda c: [])
        assert trends.get_trending_hashtags("tiktok") == []


class TestTrendsFetch:
    def test_parses_youtube_rss_without_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Sin API key, el RSS público de tendencias sigue funcionando."""
        monkeypatch.setenv("EDGETAPE_STORAGE", str(tmp_path))
        monkeypatch.delenv("EDGETAPE_TRENDS", raising=False)
        monkeypatch.delenv("EDGETAPE_YOUTUBE_API_KEY", raising=False)

        feed = (
            "<?xml version='1.0'?><feed>"
            "<entry><title>#milanuncios #emprendimiento</title></entry>"
            "</feed>"
        )

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=feed, request=request)

        real_client = httpx.Client

        class _FakeClient(real_client):  # type: ignore[misc]
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(_handler)
                super().__init__(*a, **kw)

        monkeypatch.setattr(trends.httpx, "Client", _FakeClient)
        tags = trends.get_trending_hashtags("youtube_shorts")
        assert "milanuncios" in tags, tags
        assert "emprendimiento" in tags, tags

    def test_fetch_failure_degrades_to_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Si la fuente falla, `[]` y el llamador sigue con LLM + heurístico."""
        monkeypatch.setenv("EDGETAPE_STORAGE", str(tmp_path))
        monkeypatch.delenv("EDGETAPE_TRENDS", raising=False)
        monkeypatch.delenv("EDGETAPE_YOUTUBE_API_KEY", raising=False)

        def _boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sin red", request=request)

        real_client = httpx.Client

        class _FakeClient(real_client):  # type: ignore[misc]
            def __init__(self, *a, **kw):
                kw["transport"] = httpx.MockTransport(_boom)
                super().__init__(*a, **kw)

        monkeypatch.setattr(trends.httpx, "Client", _FakeClient)
        assert trends.get_trending_hashtags("youtube_shorts") == []


class TestEnrichTags:
    def test_inserts_one_trend_within_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            trends, "get_trending_hashtags", lambda p: ["milanuncios", "delpatron"]
        )
        out = trends.enrich_tags(["pricing", "ventas", "shorts"], "tiktok", max_tags=6)

        assert len(out) <= 6
        assert out[0] == "pricing", "los tags del LLM mandan"
        assert "milanuncios" in out
        # solo UN trend, no los dos: la lista no se infla
        assert "delpatron" not in out, out

    def test_no_duplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(trends, "get_trending_hashtags", lambda p: ["pricing"])
        out = trends.enrich_tags(["pricing", "ventas"], "tiktok", max_tags=6)
        assert len(out) == len(set(out)), out

    def test_full_budget_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(trends, "get_trending_hashtags", lambda p: ["nuevo"])
        base = ["a", "b", "c", "d", "e", "f"]
        assert trends.enrich_tags(list(base), "tiktok", max_tags=6) == base
