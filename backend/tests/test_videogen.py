"""Tests del adaptador opcional de video/imagen generado por IA (offline)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from app import videogen

# PNG mínimo + relleno: `_save_bytes` descarta payloads de menos de 1 KB.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
) + bytes(2048)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured_returns_none(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("EDGETAPE_VIDEOGEN_BASE_URL", raising=False)
    assert videogen.is_configured() is False
    assert videogen.generate_asset("un cafe", (1080, 1920), tmp_path / "a") == (None, False)


def test_image_mode_returns_b64_frame(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://ia.example/v1")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_API_KEY", "sk-x")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODEL", "imagen-1")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_PNG).decode()}]})

    out = tmp_path / "scene_1.asset"
    path, is_video = videogen.generate_asset("un cafe", (1080, 1920), out, client=_client(handler))
    assert is_video is False
    assert path == out
    assert out.read_bytes() == _PNG
    assert seen["url"] == "https://ia.example/v1/images/generations"
    assert seen["auth"] == "Bearer sk-x"
    assert '"model":"imagen-1"' in seen["body"]


def test_image_mode_accepts_url_response(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://ia.example/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/f.png"}]})
        return httpx.Response(200, content=_PNG)

    out = tmp_path / "scene_2.asset"
    path, is_video = videogen.generate_asset("un cafe", (1080, 1920), out, client=_client(handler))
    assert (path, is_video) == (out, False)
    assert out.read_bytes() == _PNG


def test_webhook_mode_downloads_clip(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://video.example/gen")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODE", "webhook")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODEL", "wan-2.1")
    body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "video.example":
            body.update(json.loads(request.read().decode()))
            return httpx.Response(200, json={"video_url": "https://cdn.example/clip.mp4"})
        return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42" + b"0" * 2048)

    out = tmp_path / "scene_3.asset"
    path, is_video = videogen.generate_asset("un cafe", (1080, 1920), out, client=_client(handler))
    assert is_video is True
    assert path == out
    assert body["prompt"] == "un cafe"
    assert body["aspect"] == "9:16"
    assert body["model"] == "wan-2.1"


def test_webhook_mode_ignores_image_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://video.example/gen")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODE", "webhook")
    assert videogen.generate_image("x", (1920, 1080), tmp_path / "a") is None


def test_provider_failure_never_raises(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://ia.example/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    assert videogen.generate_asset("x", (1080, 1920), tmp_path / "a", client=_client(handler)) == (
        None,
        False,
    )


def test_empty_response_returns_none(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://ia.example/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{}]})

    assert videogen.generate_asset("x", (1080, 1920), tmp_path / "a", client=_client(handler)) == (
        None,
        False,
    )


def test_tiny_payload_is_not_saved(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://ia.example/v1")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_MODE", "webhook")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ia.example":
            return httpx.Response(200, json={"video_url": "https://cdn.example/clip.mp4"})
        return httpx.Response(200, content=b"x")

    out = tmp_path / "a.asset"
    assert videogen.generate_asset("x", (1080, 1920), out, client=_client(handler)) == (None, False)
    assert not out.exists()


# ── Integración en el motor de escenas ────────────────────────


def _scene_assets(monkeypatch, tmp_path: Path, **env) -> list[tuple[Path | None, bool]]:
    """Ejecuta el motor de escenas sin red: sin catálogo de stock ni Wikimedia."""
    from app import ai_generate

    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ai_generate.materials, "build_library", lambda: None)
    monkeypatch.setattr(
        ai_generate, "_fetch_wikimedia_images", lambda *a, **k: [None] * len(a[0])
    )
    return ai_generate._fetch_scene_media(
        ["gancho", "uno", "dos", "cierre"],
        ["g", "barista sirve cafe", "panaderia artesanal", "c"],
        (1080, 1920),
        tmp_path,
        max_total=1.0,
        per_request=1.0,
    )


def test_videogen_disabled_in_tests(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "0")
    assets = _scene_assets(monkeypatch, tmp_path, EDGETAPE_VIDEOGEN_BASE_URL="https://x/v1")
    assert assets == [(None, False)] * 4


def test_videogen_fills_scene_when_stock_missing(monkeypatch, tmp_path: Path):
    from app import ai_generate

    fake = _FakeVideogen()
    monkeypatch.setattr(ai_generate, "videogen", fake)
    assets = _scene_assets(monkeypatch, tmp_path, EDGETAPE_VIDEOGEN_BASE_URL="https://x/v1")
    assert fake.calls == 1  # presupuesto de 1 escena
    assert assets[1][0] == tmp_path / "scene_1.asset"
    assert assets[1][1] is False
    assert assets[0][0] is None  # el gancho nunca usa material generado
    assert assets[3][0] is None  # el cierre tampoco


def test_videogen_budget_is_configurable(monkeypatch, tmp_path: Path):
    from app import ai_generate

    fake = _FakeVideogen()
    monkeypatch.setattr(ai_generate, "videogen", fake)
    assets = _scene_assets(
        monkeypatch,
        tmp_path,
        EDGETAPE_VIDEOGEN_BASE_URL="https://x/v1",
        EDGETAPE_VIDEOGEN_MAX_SCENES="2",
    )
    assert fake.calls == 2
    assert assets[1][0] is not None and assets[2][0] is not None


def test_videogen_zero_budget_is_respected(monkeypatch, tmp_path: Path):
    from app import ai_generate

    fake = _FakeVideogen()
    monkeypatch.setattr(ai_generate, "videogen", fake)
    assets = _scene_assets(
        monkeypatch,
        tmp_path,
        EDGETAPE_VIDEOGEN_BASE_URL="https://x/v1",
        EDGETAPE_VIDEOGEN_MAX_SCENES="0",
    )
    assert fake.calls == 0
    assert all(path is None for path, _ in assets)


def test_videogen_flag_disables_provider(monkeypatch, tmp_path: Path):
    from app import ai_generate

    fake = _FakeVideogen()
    monkeypatch.setattr(ai_generate, "videogen", fake)
    _scene_assets(
        monkeypatch, tmp_path, EDGETAPE_VIDEOGEN_BASE_URL="https://x/v1", EDGETAPE_VIDEOGEN="0"
    )
    assert fake.calls == 0


def test_stock_wins_over_videogen(monkeypatch, tmp_path: Path):
    """Si el catálogo entrega material, el proveedor de pago no se toca."""
    from app import ai_generate

    fake = _FakeVideogen()
    monkeypatch.setattr(ai_generate, "videogen", fake)
    monkeypatch.setattr(ai_generate.materials, "build_library", lambda: _FakeLibrary())
    monkeypatch.setattr(ai_generate.materials, "download", lambda *a, **k: bool(a[2].write_bytes(_PNG)) or True)
    monkeypatch.setattr(
        ai_generate, "_fetch_wikimedia_images", lambda *a, **k: [None] * len(a[0])
    )
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    monkeypatch.setenv("EDGETAPE_VIDEOGEN_BASE_URL", "https://x/v1")
    assets = ai_generate._fetch_scene_media(
        ["gancho", "uno", "dos", "cierre"],
        # queries en inglés: el validador descarta las de español y esa escena
        # caería al proveedor de pago, que es justamente lo que este test no quiere
        ["cafe", "barista", "bakery counter", "gracias"],
        (1080, 1920),
        tmp_path,
        max_total=1.0,
        per_request=1.0,
    )
    assert fake.calls == 0
    assert assets[1][0] is not None
    assert assets[2][0] is not None


class _FakeVideogen:
    def __init__(self):
        self.calls = 0

    @staticmethod
    def is_configured() -> bool:
        return True

    def generate_asset(self, prompt, size, out, client=None):
        self.calls += 1
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake")
        return out, False


class _FakePick:
    kind = "video"
    provider = "pexels"


class _FakeLibrary:
    def search(self, query, want_landscape, client=None):
        return [_FakePick()]

    def take(self, picks):
        return _FakePick()


def test_spanish_query_never_reaches_stock(monkeypatch, tmp_path: Path):
    """Una query en español no se envía a Pexels: se pierde presupuesto y no
    devuelve material que ilustre la escena (era 8 de 31 escenas con b-roll)."""
    from app import ai_generate

    searched: list[str] = []

    class _Recording(_FakeLibrary):
        def search(self, query, want_landscape, client=None):
            searched.append(query)
            return []

        def take(self, picks):
            return None

    monkeypatch.setattr(ai_generate, "videogen", _FakeVideogen())
    monkeypatch.setattr(ai_generate.materials, "build_library", lambda: _Recording())
    monkeypatch.setattr(
        ai_generate, "_fetch_wikimedia_images", lambda *a, **k: [None] * len(a[0])
    )
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")

    ai_generate._fetch_scene_media(
        ["gancho", "uno", "dos", "cierre"],
        ["cafe", "saber hacer especial", "perro corriendo", "gracias"],
        (1080, 1920),
        tmp_path,
        max_total=1.0,
        per_request=1.0,
    )
    # las escenas 1 y 2 son las de cuerpo: ninguna query llegó al buscador
    assert searched == []

