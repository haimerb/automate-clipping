"""Cadena de proveedores de material IA (`videogen`).

Sin GPU local (6 GB VRAM) no hay difusión de video posible, así que el motor de
escenas tiene que poder apoyarse en proveedores remotos. Estos tests fijan que:

1. `auto` respeta `EDGETAPE_VIDEOGEN_MODE` y cae en `image` si no hay URL.
2. La cadena `EDGETAPE_VIDEOGEN_PROVIDERS` intenta en orden y el primero que
   responde gana.
3. Un proveedor que falla/da 429 pasa al siguiente sin tumbar el job.
4. `EDGETAPE_VIDEOGEN_MAX_GENERATIONS` evita regenerar el mismo prompt.
5. Replicate hace POST + poll; fal descarga la URL de `video`.

Sin red: todo va por `httpx.MockTransport`.
"""

import base64
import json

import httpx
import pytest

from app import videogen


@pytest.fixture(autouse=True)
def _clear_gen_cache():
    videogen._GENERATION_CACHE.clear()
    yield
    videogen._GENERATION_CACHE.clear()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestProviderChainOrder:
    def test_auto_uses_mode_when_base_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://x.test")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODE", "webhook")
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_PROVIDERS", raising=False)
        assert videogen._provider_chain() == ("webhook",)

    def test_auto_defaults_to_image(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://x.test")
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_MODE", raising=False)
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_PROVIDERS", raising=False)
        assert videogen._provider_chain() == ("image",)

    def test_explicit_chain_is_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "fal,hf,image")
        assert videogen._provider_chain() == ("fal", "hf", "image")

    def test_unknown_providers_are_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "fal,nope,image")
        assert videogen._provider_chain() == ("fal", "image")

    def test_is_configured_sees_hosted_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_BASE_URL", raising=False)
        for key in (
            "EDGETAPE_VIDEOGEN_HF_TOKEN",
            "EDGETAPE_VIDEOGEN_FAL_KEY",
            "EDGETAPE_VIDEOGEN_REPLICATE_TOKEN",
            "EDGETAPE_VIDEOGEN_HF_SPACE_TOKEN",
        ):
            monkeypatch.delenv(key, raising=False)
        assert not videogen.is_configured()
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_FAL_KEY", "fal-k")
        assert videogen.is_configured()


class TestChainFallback:
    def test_falls_through_to_second_provider(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Si `image` falla, `fal` responde y el material se guarda."""
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "image,fal")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://img.test")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_FAL_KEY", "fal-k")

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 2048
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if "img.test" in str(request.url):
                return httpx.Response(500, text="caido", request=request)
            if str(request.url).startswith("https://fal.run"):
                return httpx.Response(
                    200, json={"video": "https://cdn.test/v.mp4"}, request=request
                )
            return httpx.Response(200, content=png, request=request)

        c = _client(handler)
        path, is_video = videogen.generate_asset(
            "un cafe sobre la mesa", (1080, 1920), tmp_path / "a.asset", client=c
        )
        c.close()

        assert path is not None
        assert is_video is True
        assert path.read_bytes() == png
        assert any("img.test" in u for u in seen)
        assert any("fal.run" in u for u in seen)

    def test_all_fail_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Si nadie responde: `(None, False)` y el pipeline sigue con Wikimedia."""
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "image")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://img.test")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="no", request=request)

        c = _client(handler)
        out = videogen.generate_asset("x y z", (1080, 1920), tmp_path / "b.asset", client=c)
        c.close()
        assert out == (None, False)

    def test_rate_limit_moves_to_next(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """429 en el primero no es fatal: el segundo proveedor entra."""
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "image,hf")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://img.test")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_HF_TOKEN", "hf-t")
        mp4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 2048

        def handler(request: httpx.Request) -> httpx.Response:
            if "img.test" in str(request.url):
                return httpx.Response(429, text="quota", request=request)
            if "huggingface.co" in str(request.url):
                return httpx.Response(
                    200,
                    content=mp4,
                    headers={"content-type": "video/mp4"},
                    request=request,
                )
            return httpx.Response(200, content=mp4, request=request)

        c = _client(handler)
        path, is_video = videogen.generate_asset(
            "un perro corriendo", (1080, 1920), tmp_path / "c.asset", client=c
        )
        c.close()
        assert path is not None and is_video is True


class TestGenerationBudget:
    def test_max_generations_blocks_repeat(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_MAX_GENERATIONS", "1")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "fal")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_FAL_KEY", "fal-k")
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).startswith("https://fal.run"):
                calls["n"] += 1
                return httpx.Response(
                    200, json={"video": "https://cdn.test/v.mp4"}, request=request
                )
            return httpx.Response(200, content=b"\x00" * 2048, request=request)

        c = _client(handler)
        first, _ = videogen.generate_asset(
            "misma escena", (1080, 1920), tmp_path / "d1.asset", client=c
        )
        second, _ = videogen.generate_asset(
            "misma escena", (1080, 1920), tmp_path / "d2.asset", client=c
        )
        c.close()
        assert first is not None
        assert second is None, "el segundo intento debe agotar el presupuesto"
        assert calls["n"] == 1

    def test_zero_means_unlimited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_MAX_GENERATIONS", "0")
        assert videogen._max_generations_per_job() == 0
        assert videogen._generation_allowed("p", "fal") is True


class TestReplicatePoll:
    def test_post_then_poll(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "replicate")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_REPLICATE_TOKEN", "rp-t")
        monkeypatch.setattr(videogen.time, "sleep", lambda s: None)
        mp4 = b"\x00\x00\x00\x18ftypmp42" + b"1" * 2048
        polls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/predictions"):
                return httpx.Response(
                    200,
                    json={
                        "status": "starting",
                        "urls": {"get": "https://api.replicate.com/v1/p/1"},
                    },
                    request=request,
                )
            if "/p/1" in url:
                polls["n"] += 1
                if polls["n"] < 3:
                    return httpx.Response(
                        200, json={"status": "processing"}, request=request
                    )
                return httpx.Response(
                    200,
                    json={"status": "succeeded", "output": "https://cdn.test/v.mp4"},
                    request=request,
                )
            return httpx.Response(200, content=mp4, request=request)

        c = _client(handler)
        path, is_video = videogen.generate_asset(
            "cielo al atardecer", (1920, 1080), tmp_path / "e.asset", client=c
        )
        c.close()
        assert path is not None and is_video is True
        assert polls["n"] == 3

    def test_failed_prediction_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "replicate")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_REPLICATE_TOKEN", "rp-t")

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/predictions"):
                return httpx.Response(
                    200,
                    json={"status": "starting", "urls": {"get": "https://api.replicate.com/v1/p/9"}},
                    request=request,
                )
            return httpx.Response(
                200, json={"status": "failed", "error": "NSFW"}, request=request
            )

        c = _client(handler)
        out = videogen.generate_asset("algo raro", (1080, 1920), tmp_path / "f.asset", client=c)
        c.close()
        assert out == (None, False)


class TestImageStillWorks:
    def test_b64_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_PROVIDERS", "image")
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://img.test")
        blob = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"2" * 2048).decode()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [{"b64_json": blob}]}, request=request
            )

        c = _client(handler)
        path, is_video = videogen.generate_asset(
            "un bosque", (1080, 1920), tmp_path / "g.asset", client=c
        )
        c.close()
        assert path is not None
        assert is_video is False
        assert path.read_bytes().startswith(b"\x89PNG")

    def test_not_configured_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_BASE_URL", raising=False)
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_HF_TOKEN", raising=False)
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_FAL_KEY", raising=False)
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_REPLICATE_TOKEN", raising=False)
        monkeypatch.delenv("EDGETAPE_VIDEOGEN_HF_SPACE_TOKEN", raising=False)
        out = videogen.generate_asset("x", (1080, 1920), tmp_path / "h.asset")
        assert out == (None, False)

    def test_empty_prompt_returns_none(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://img.test")
        assert videogen.generate_asset("   ", (1080, 1920), tmp_path / "i.asset") == (
            None,
            False,
        )
