from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ai_generate as aig
from app.ai_generate import _size_for
from app.main import create_app
from app.media import probe_duration
from app.processing import run_job
from app.storage import JobStore
from app.transcriber import MockTranscriber

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)

PROMPT = "El secreto para vender es entender la emoción antes que el producto."


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "storage", MockTranscriber()))


def _video_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return stream["width"], stream["height"]


def _write_generate_meta(store: JobStore, job_id: str, **overrides) -> None:
    meta = {
        "prompt": PROMPT,
        "duration": 8,
        "style": "professional",
        "platform": "youtube_shorts",
        "voice": "es_mx_female",
        "auto_publish": False,
        "account_id": None,
        "auto_publish_account": None,
        **overrides,
    }
    (store.job_dir(job_id) / "generate_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )


_FAKE_SCRIPT = {
    "title": "Vender es entender la emoción",
    "hook": "¿Vendes o entiendes a tu cliente?",
    "script": (
        "La mayoría de las marcas empujan el producto antes de escuchar. "
        "Quien entiende la emoción vende sin insistir. "
        "Primero pregunta, después ofrece. "
        "La confianza se construye en cada conversación honesta. "
        "Ese es el cambio que mueve la aguja."
    ),
    "sentences": [
        "La mayoría de las marcas empujan el producto antes de escuchar.",
        "Quien entiende la emoción vende sin insistir.",
        "Primero pregunta, después ofrece.",
        "La confianza se construye en cada conversación honesta.",
        "Ese es el cambio que mueve la aguja.",
    ],
    "tags": ["ventas", "marketing", "empatia"],
    "queries": [
        "shop owner talking",
        "customer handshake",
        "team meeting office",
        "person smiling conversation",
        "sunrise over city",
    ],
}


def _stub_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """El guion lo escribe el LLM; en tests se inyecta uno fijo (sin red)."""
    monkeypatch.setattr(
        "app.ai_generate.write_script", lambda *a, **k: dict(_FAKE_SCRIPT)
    )


# ── endpoint /api/generate ───────────────────────────────────


def test_generate_requires_auth(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/generate", json={"prompt": "hola", "duration": 15})
    assert resp.status_code == 401


def test_generate_endpoint_validations(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)

    # prompt vacío
    assert (
        client.post("/api/generate", json={"prompt": "   "}, headers=auth_headers).status_code
        == 422
    )
    # duración fuera del set permitido
    resp = client.post("/api/generate", json={"prompt": PROMPT, "duration": 45}, headers=auth_headers)
    assert resp.status_code == 422
    # duración sobre el máximo de youtube_shorts (60s)
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 120, "platform": "youtube_shorts"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # YouTube video largo arranca en 6 minutos: por debajo del piso → 422
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 120, "platform": "youtube"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # 6 min exactos → OK
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 360, "platform": "youtube"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    # 15 min (máximo de YouTube largo) → OK
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 900, "platform": "youtube"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    # sobre el nuevo máximo (15 min) → 422
    assert (
        client.post(
            "/api/generate",
            json={"prompt": PROMPT, "duration": 960, "platform": "youtube"},
            headers=auth_headers,
        ).status_code
        == 422
    )


def test_generate_endpoint_creates_job(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    client = _client(tmp_path)
    store = JobStore(storage)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)
    resp = client.post("/api/generate", json={"prompt": PROMPT, "duration": 15}, headers=auth_headers)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = store.get_job(job_id)
    assert job is not None
    assert job.source == "generate"
    assert job.owner_id

    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == PROMPT
    assert meta["duration"] == 15
    assert meta["platform"] == "youtube_shorts"


def test_generate_endpoint_resolves_account(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = tmp_path / "storage"
    client = _client(tmp_path)
    store = JobStore(storage)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)

    created = client.post(
        "/api/accounts",
        json={"platform": "youtube_shorts", "name": "Mi canal corto", "handle": "@micv"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 15, "auto_publish": True, "account_id": account_id},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert meta["auto_publish"] is True
    assert meta["auto_publish_account"] == "Mi canal corto"

    # cuenta inexistente → 422 sin crear job
    resp = client.post(
        "/api/generate",
        json={"prompt": PROMPT, "duration": 15, "auto_publish": True, "account_id": "no-existe"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ── pipeline (run_job, source="generate") ────────────────────


def _run_generate_job(
    tmp_path: Path,
    user_id: str,
    monkeypatch: pytest.MonkeyPatch,
    **meta_overrides,
) -> tuple[JobStore, str, list[tuple]]:
    storage = tmp_path / "storage"
    store = JobStore(storage)
    job = store.create_job(
        f"IA: {PROMPT[:40]}", source="generate", source_url=None, owner_id=user_id
    )
    _write_generate_meta(store, job.id, **meta_overrides)
    called: list[tuple] = []

    def _fake_enqueue(*args, **kwargs):
        called.append((args, kwargs))

    monkeypatch.setattr("app.ai_generate.build_voiceover", lambda *a, **k: None)
    monkeypatch.setattr("app.tasks.enqueue_auto_publish", _fake_enqueue)
    _stub_script(monkeypatch)
    asyncio.run(run_job(job.id, store, MockTranscriber()))
    return store, job.id, called


def test_run_job_generate_vertical_short(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short real end-to-end: source vertical 9:16, clip exportado, metadata y auto-publish."""
    store, job_id, enqueued = _run_generate_job(
        tmp_path, user_id, monkeypatch, auto_publish=True, auto_publish_account="Canal Auto"
    )

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.transcriber == "ai_generate"
    assert job.scorer == "ai_generate"
    assert job.clip_count == 1
    assert job.auto_publish is True
    assert job.auto_publish_platform == "youtube_shorts"
    assert job.auto_publish_account == "Canal Auto"

    # la fuente real generada es vertical 9:16 (1080x1920)
    assert _video_size(store.source_path(job_id)) == (1080, 1920)

    clips = store.get_clips(job_id)
    assert len(clips) == 1
    clip = clips[0]
    assert clip.exported is True
    assert clip.export_name
    assert clip.title
    assert len(clip.script.strip()) >= 10
    exported = store.exports_dir(job_id) / clip.export_name
    assert exported.exists()
    assert _video_size(exported) == (1080, 1920)
    assert 0 < probe_duration(exported) <= 9.0

    # el guion del LLM (o su fallback) queda persistido para reuso
    meta = json.loads((store.job_dir(job_id) / "generate_meta.json").read_text(encoding="utf-8"))
    assert "script_gen" in meta
    assert meta["script_gen"]["hook"]

    # auto-publish encolado con la cuenta destino
    assert any(
        args
        and args[0] == job_id
        and args[1] == clip.id
        and args[3] == "youtube_shorts"
        and args[4] == "Canal Auto"
        for args, _ in enqueued
    ), enqueued


def test_run_job_generate_youtube_horizontal(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube video largo: platform=youtube produce fuente horizontal 16:9."""
    store, job_id, _ = _run_generate_job(tmp_path, user_id, monkeypatch, platform="youtube")

    job = store.get_job(job_id)
    assert job is not None and job.status == "done", job.error if job else "job not found"
    assert job.clip_count == 1
    assert _video_size(store.source_path(job_id)) == (1920, 1080)

    clips = store.get_clips(job_id)
    assert clips and clips[0].exported is True
    exported = store.exports_dir(job_id) / clips[0].export_name
    assert exported.exists()
    assert _video_size(exported) == (1920, 1080)


def test_generate_source_respects_meta_prompt(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La fuente generada se usa igual que cualquier otra: se exporta y el clip la refleja."""
    store, job_id, _ = _run_generate_job(tmp_path, user_id, monkeypatch)
    clips = store.get_clips(job_id)
    assert clips
    script = clips[0].script.strip()
    # sin LLM, el fallback expande el prompt a un guion con la frase del tema
    assert len(script) > 80
    assert len(clips[0].line or "") > 0
    assert clips[0].exported and clips[0].export_name


def test_ai_generate_scene_count_follows_words_not_duration() -> None:
    """Una escena ≈ WORDS_PER_SCENE palabras (antes: 1 escena cada 40s fijos)."""
    assert aig.WORD_RATE == 2.2
    # calibrado contra gpt-oss-20b: se le piden 25 y escribe ~13-14
    assert aig.WORDS_PER_SCENE == 14
    # 360s a 2.2 palabras/s = 792 palabras = ~57 escenas de 14 palabras
    assert aig._scene_count(360) == 57
    # 15s da el mínimo (4 escenas), no 1
    assert aig._scene_count(15) == aig.SCENES_MIN
    # 900s (15 min) queda acotado por SCENES_MAX
    assert aig._scene_count(900) == aig.SCENES_MAX
    # un formato largo da escenas cortas, no oraciones de 90 palabras
    for dur in (180, 360, 600, 900):
        n = aig._scene_count(dur)
        words_per_scene = int(dur * aig.WORD_RATE) / n
        assert words_per_scene <= 25, (dur, n, words_per_scene)
        # ~6-10s de plano por escena: ritmo de narrado largo, no un plano de 40s
        assert 4.0 <= dur / n <= 11.0, (dur, n, dur / n)


def test_ai_generate_scene_blocks_split_long_scripts() -> None:
    """El guion largo se pide en bloques de SCRIPT_BLOCK_SCENES escenas."""
    spans = aig._scene_blocks(32)
    assert len(spans) == 4
    assert spans[0] == (0, aig.SCRIPT_BLOCK_SCENES)
    assert spans[-1][1] == 32
    # la última escena no se pierde en el reparto
    assert sum(b - a for a, b in spans) == 32
    # un short cabe en un solo bloque
    assert len(aig._scene_blocks(aig._scene_count(15))) == 1
    # todo guion largo se parte (defensa contra volver al request único)
    assert len(aig._scene_blocks(aig._scene_count(360))) > 1


# ── queries visuales ─────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "city skyline at night",
        "happy family cooking",
        "woman running marathon",
        "sunrise over mountains",
    ],
)
def test_ai_generate_usable_query_accepted(query: str) -> None:
    assert aig.is_usable_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "",                       # vacía
        "saber",                  # una sola palabra
        "saber hacer especial",    # stemmed keywords del guion en español
        "entender historia mirar", # la query que veía el log de Pexels
        "para que puedes",        # conectores en español
        "ciudad historia",         # tema en vez de imagen
        "corazónLatino",          # ñ: no es query en inglés
        "año nuevo",              # con tilde
    ],
)
def test_ai_generate_garbage_query_rejected(query: str) -> None:
    """Lo que antes se mandaba a Pexels tal cual y no devolvía nada útil."""
    assert aig.is_usable_query(query) is False


@pytest.mark.parametrize(
    "query",
    ["City Skyline at Night", "Sunrise Over The Beach"],
)
def test_ai_generate_titlecase_query_accepted(query: str) -> None:
    """Title case es solo capitalización: Pexels lo indexa bien, no se rechaza."""
    assert aig.is_usable_query(query) is True



def test_ai_generate_fetch_scene_media_skips_bad_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una query en español no se envía a Pexels: la escena cae a Wikimedia."""
    searched: list[str] = []
    monkeypatch.setenv("EDGETAPE_AI_IMAGES", "1")
    monkeypatch.setenv("EDGETAPE_PEXELS_API_KEY", "k")
    monkeypatch.setenv("EDGETAPE_PIXABAY_API_KEY", "")
    monkeypatch.setattr("app.materials.download", lambda *a, **k: False)

    class _Lib:
        def search(self, query, *a, **k):
            searched.append(query)
            return []

        def take(self, picks):
            return picks[0] if picks else None

    monkeypatch.setattr("app.materials.build_library", lambda: _Lib())
    monkeypatch.setattr("app.ai_generate._fetch_wikimedia_images", lambda *a, **k: [None] * 5)

    # las escenas 0 (título) y 4 (end card) no buscan material por diseño
    sentences = ["a.", "b.", "c.", "d.", "e."]
    queries = ["cat sleeping", "city skyline", "saber hacer especial", "sunrise beach", "dog running"]
    aig._fetch_scene_media(sentences, queries, (1080, 1920), tmp_path)

    # de las 3 escenas de cuerpo solo llegaron al buscador las 2 queries en inglés
    assert set(searched) == {"city skyline", "sunrise beach"}
    # las tarjetas ni se buscan aunque la query sea buena
    assert "cat sleeping" not in searched
    assert "dog running" not in searched


# ── duración exacta ───────────────────────────────────────────


def test_ai_generate_fit_audio_compresses_to_exact_duration(tmp_path: Path) -> None:
    """La locución más larga que el slot se acelera, no estira el video."""
    long_audio = tmp_path / "long.m4a"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=18",
            "-c:a", "aac", str(long_audio),
        ],
        check=True,
    )
    out = tmp_path / "fitted.m4a"
    fitted = aig._fit_audio(str(long_audio), 15.0, out)
    assert fitted is not None and Path(fitted).exists()
    assert 14.5 <= probe_duration(fitted) <= 15.5


def test_ai_generate_fit_audio_pads_short_voiceover(tmp_path: Path) -> None:
    """La locución más corta se rellena con silencio hasta el final."""
    short_audio = tmp_path / "short.m4a"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:a", "aac", str(short_audio),
        ],
        check=True,
    )
    out = tmp_path / "padded.m4a"
    fitted = aig._fit_audio(str(short_audio), 15.0, out)
    assert fitted is not None
    assert 14.5 <= probe_duration(fitted) <= 15.5


def test_ai_generate_fit_audio_keeps_matching_duration(tmp_path: Path) -> None:
    """Si ya dura lo pedido no se reprocesa (devuelve la ruta original)."""
    audio = tmp_path / "ok.m4a"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=15",
            "-c:a", "aac", str(audio),
        ],
        check=True,
    )
    assert aig._fit_audio(str(audio), 15.0, tmp_path / "nope.m4a") == str(audio)
    assert not (tmp_path / "nope.m4a").exists()


def test_ai_generate_card_seconds_are_capped() -> None:
    """La tarjeta de título y la end card duran 1,5-3s, no se comen el video."""
    assert aig._card_seconds(15) == 1.5
    assert aig._card_seconds(60) == 3.0
    assert aig._card_seconds(900) == 3.0


def test_ai_generate_title_and_end_cards_do_not_eat_video() -> None:
    """En 15s con 4 escenas las tarjetas no se llevan 7,5s de los 15."""
    sentences = [f"Escena {i} de cuerpo con unas cuantas palabras." for i in range(4)]
    total = 15.0
    card = aig._card_seconds(total)
    starts, ends = aig._sentence_timings(sentences, total, card, card)
    assert len(starts) == len(ends) == 4
    assert starts == sorted(starts) and ends == sorted(ends)
    # contiguo y sin huecos
    assert starts[0] == 0.0 and ends[-1] == total
    for i in range(3):
        assert abs(ends[i] - starts[i + 1]) < 1e-6
    # la tarjeta de título y la end card están acotadas
    assert abs((ends[0] - starts[0]) - card) < 1e-6
    assert abs((ends[-1] - starts[-1]) - card) < 1e-6
    # el cuerpo se queda con el resto
    body = (ends[2] - starts[1])
    assert body >= total - 2 * card - 1e-6
    assert body > 6.0
    # sin head/tail el comportamiento antiguo se mantiene
    plain_s, plain_e = aig._sentence_timings(sentences, total)
    assert plain_s[0] == 0.0 and plain_e[-1] == total


# ── LLM del guion: presupuesto de tokens y fallo explícito ───


class _LLM:
    """MockTransport que captura los payloads y devuelve respuestas preparadas."""

    def __init__(self, responses: list, status: int = 200) -> None:
        self.responses = list(responses)
        self.status = status
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        if self.status != 200:
            return httpx.Response(self.status, text="error", request=request)
        body = self.responses.pop(0) if self.responses else ""
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": body}, "finish_reason": "stop"}
                ]
            },
            request=request,
        )


def _llm_env(monkeypatch: pytest.MonkeyPatch, model: str = "openai/gpt-oss-20b") -> None:
    monkeypatch.setenv("EDGETAPE_LLM_BASE_URL", "https://api.test/v1")
    monkeypatch.setenv("EDGETAPE_LLM_MODEL", model)
    monkeypatch.setenv("EDGETAPE_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("EDGETAPE_GROQ_API_KEY", "")


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, transport) -> None:
    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.ai_generate.httpx.Client", _client)


def test_ai_generate_complete_sends_token_budget_and_low_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gpt-oss se come el presupuesto pensando: hay que cappingarlo y bajar el effort.

    Sin esto Groq devuelve 2048 tokens consumidos, `content=""` y
    `finish_reason="length"` — el guion vacío que venía del fallback.
    """
    _llm_env(monkeypatch)
    llm = _LLM(['{"ok": true}'])
    _patch_httpx(monkeypatch, httpx.MockTransport(llm))

    out = aig._complete("sys", "user", max_tokens=1200)
    assert out == '{"ok": true}'
    payload = llm.payloads[0]
    assert payload["reasoning_effort"] == "low"
    assert payload["max_completion_tokens"] >= 1200


@pytest.mark.parametrize(
    "label,raw",
    [
        (
            "comillas sueltas en el guion",
            '{"title": "T", "script": "El dijo \\"hola\\" y se fue. Luego '
            'volvio bien a su casa.", "queries": ["x y"]}',
        ),
        (
            "salto de linea crudo",
            '{\n "script": "Uno dice \\"si\\".\nDos dice \\"no\\" al final.",\n'
            ' "queries": ["a b", "c d"],}',
        ),
        (
            "coma suelta antes del cierre",
            '{"script": "Uno. Dos. Tres.", "queries": ["a b", "c d"],}',
        ),
        (
            "fence de markdown",
            '```json\n{"title": "T", "script": "Uno. Dos. Tres. Cuatro.", '
            '"queries": ["a b", "c d"]}\n```',
        ),
    ],
)
def test_ai_generate_parses_messy_llm_json(label: str, raw: str) -> None:
    """El LLM rompe el formato JSON de formas previsibles: hay que repararlas.

    Antes, un JSON roto en el bloque 3 de 8 tumbaba el guion entero.
    """
    parsed = aig._parse_script_json(raw)
    assert parsed["script"]
    assert len(parsed["script"]) >= 10, label
    assert parsed["queries"], label


def test_ai_generate_complete_raises_on_empty_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`content=""` es un fallo, no un guion vacío: debe levantar, no devolver ''."""
    _llm_env(monkeypatch)

    def _empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
            request=request,
        )

    monkeypatch.setattr("app.ai_generate.time.sleep", lambda *_: None)
    _patch_httpx(monkeypatch, httpx.MockTransport(_empty))

    with pytest.raises(aig.ScriptGenerationError, match="guion"):
        aig._complete("sys", "user")


def test_ai_generate_complete_rejects_dead_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un 400 no se reintenta (modelo dado de baja): el guion no se puede escribir."""
    _llm_env(monkeypatch, model="gemma2-9b-it")
    llm = _LLM([], status=400)
    _patch_httpx(monkeypatch, httpx.MockTransport(llm))

    with pytest.raises(aig.ScriptGenerationError, match="400"):
        aig._complete("sys", "user")
    # sin reintentos: un solo request
    assert len(llm.payloads) == 1


def test_ai_generate_complete_drops_reasoning_effort_on_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un endpoint que no conoce `reasoning_effort` se reintenta sin él."""
    _llm_env(monkeypatch, model="gpt-4o-mini")
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        if "reasoning_effort" in payload:
            return httpx.Response(400, text="unknown param", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hola"}, "finish_reason": "stop"}]},
            request=request,
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    assert aig._complete("sys", "user") == "hola"
    assert "reasoning_effort" not in calls[-1]


def test_ai_generate_complete_raises_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin LLM el job debe fallar, no inventar un guion de relleno."""
    monkeypatch.setenv("EDGETAPE_LLM_BASE_URL", "")
    monkeypatch.setenv("EDGETAPE_LLM_MODEL", "")
    monkeypatch.setenv("EDGETAPE_GROQ_API_KEY", "")
    with pytest.raises(aig.ScriptGenerationError, match="no hay LLM configurado"):
        aig.write_script(PROMPT, 30.0, "professional", "youtube_shorts")


def test_ai_generate_parses_malformed_json_from_llm() -> None:
    """`_loads_lenient` repara los formatos que emitted gpt-oss-20b de verdad.

    Regresión del fallo reportado: `Expecting ':' delimiter: line 1 column 203`
    viene de un campo huérfano o una coma perdida entre campos.
    """
    Q = chr(34)
    casos = {
        # coma perdida entre campos
        "coma_faltante": '{' + Q + 'script' + Q + ': ' + Q + 'frase valida' + Q
                         + ' ' + Q + 'queries' + Q + ': [' + Q + 'a' + Q + ']}',
        # clave huérfana sin ':' (el error exacto reportado)
        "campo_huerfano": '{' + Q + 'script' + Q + ': ' + Q + 'frase valida' + Q
                          + ', ' + Q + 'orphan' + Q + ' ' + Q + 'valor' + Q + '}',
        # separador ';' en vez de coma
        "punto_coma": '{' + Q + 'script' + Q + ': ' + Q + 'frase valida' + Q
                      + '; ' + Q + 'queries' + Q + ': []}',
        # comas entre campos de array perdidas
        "comas_perdidas": '{' + Q + 'script' + Q + ': ' + Q + 'frase valida' + Q
                          + ', ' + Q + 'queries' + Q + ': [' + Q + 'a' + Q
                          + ' ' + Q + 'b' + Q + ']}',
    }
    for nombre, blob in casos.items():
        data = aig._loads_lenient(blob)
        assert data["script"] == "frase valida", (nombre, data)


def test_ai_generate_default_groq_model_is_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """El default directo de Groq no puede ser un modelo dado de baja."""
    monkeypatch.delenv("EDGETAPE_GROQ_MODEL", raising=False)
    assert aig.GROQ_SCRIPT_MODEL == "openai/gpt-oss-20b"
    assert "gemma" not in aig.GROQ_SCRIPT_MODEL


def _fake_block_prompt(n: int = 8, words_each: int = 25) -> str:
    """Bloque de escenas creíble: oraciones largas (pasa el filtro de 3 palabras)
    y suficientes palabras para que no se dispare el reintento de bloque corto."""
    sentences = ". ".join(
        " ".join(f"palabra{i}{j}" for j in range(words_each)) for i in range(n)
    ) + "."
    return json.dumps({
        "title": "El tema en detalle",
        "hook": "¿Por qué importa?",
        "tags": ["tema"],
        "script": sentences,
        "queries": [f"scene number {i}" for i in range(n)],
    })


def test_ai_generate_write_script_chunks_long_video(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un video de 6 min se pide en varios bloques y se concatena sin perder escenas."""
    _llm_env(monkeypatch)
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": _fake_block_prompt()}, "finish_reason": "stop"}
                ]
            },
            request=request,
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    info = aig.write_script(PROMPT, 360.0, "professional", "youtube")

    nscenes = aig._scene_count(360.0)
    nblocks = len(aig._scene_blocks(nscenes))
    assert nblocks > 1, "un guion de 6 min debe partirse"
    # un request por bloque: el guion entra en el presupuesto de tokens
    assert len(calls) == nblocks
    # el primero trae la metadata, el resto solo escenas
    assert info["title"] == "El tema en detalle"
    assert info["hook"] == "¿Por qué importa?"
    assert info["tags"] == ["tema"]
    # los bloques se concatenan en orden (topado por SCENES_MAX_SENTENCES)
    assert len(info["sentences"]) == min(8 * nblocks, aig.SCENES_MAX_SENTENCES)
    assert len(info["queries"]) == len(info["sentences"])
    assert all(p["max_completion_tokens"] > 0 for p in calls)
    # el 2º bloque recibe el contexto del 1º (las 3 últimas oraciones, para no repetir)
    assert "Lo último que escribiste" in calls[1]["messages"][1]["content"]
    assert "palabra724" in calls[1]["messages"][1]["content"]


def test_ai_generate_write_script_truncates_on_bad_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un bloque ilegible a mitad NO tira el guion: conserva el resto y avisa.

    Regresión del fallo reportado: `bloque 3/8 de escenas ilegible:
    Expecting ':' delimiter` tumbaba los 7 bloques ya buenos.
    """
    _llm_env(monkeypatch)
    # bloque 3 irrecuperable: ni JSON ni un `script` rescatable por regex
    bad = "Claro! Aqui tienes lo que me pediste, espero que sirva."
    n = {"i": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        i = n["i"]
        n["i"] += 1
        # índices 2 y 3 = los dos intentos del bloque 3
        content = bad if i in (2, 3) else _fake_block_prompt()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]},
            request=request,
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    info = aig.write_script(PROMPT, 360.0, "professional", "youtube")

    nblocks = len(aig._scene_blocks(aig._scene_count(360.0)))
    # sobrevivieron los bloques 1, 2, 4..8 (7 de 8)
    assert len(info["sentences"]) == (nblocks - 1) * 8
    # y el truncado queda explícito: nada de degradación silenciosa
    assert info["warnings"], "un guion truncado debe avisar"
    assert any("3/" in w and "truncado" in w for w in info["warnings"]), info["warnings"]


def test_ai_generate_first_bad_block_still_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el PRIMER bloque falla no hay guion que conservar: el job debe fallar."""
    _llm_env(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "no hay json aqui"},
                               "finish_reason": "stop"}]},
            request=request,
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    with pytest.raises(aig.ScriptGenerationError):
        aig.write_script(PROMPT, 360.0, "professional", "youtube")


def test_ai_generate_write_script_retries_short_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un bloque corto se reintenta: si no, el video queda mudo a la mitad."""
    _llm_env(monkeypatch)
    # 3 oraciones válidas (≥3 palabras) pero muy por debajo del presupuesto
    short = json.dumps({
        "title": "T", "hook": "H",
        "script": "Primera frase aqui. Segunda frase aqui. Tercera frase aqui.",
        "queries": ["a b", "c d", "e f"],
    })
    lengths: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        lengths.append(1)
        body = short if len(lengths) == 1 else _fake_block_prompt()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": body}, "finish_reason": "stop"}]},
            request=request,
        )

    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))
    info = aig.write_script(PROMPT, 360.0, "professional", "youtube")

    # 2 requests para el primer bloque (corto + reintento) y 1 por cada resto
    nblocks = len(aig._scene_blocks(aig._scene_count(360.0)))
    assert len(lengths) == nblocks + 1
    assert len(info["sentences"]) > 3


def test_ai_generate_write_script_short_is_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un short cabe en un solo request."""
    _llm_env(monkeypatch)
    llm = _LLM([_fake_block_prompt(4, 12)])
    _patch_httpx(monkeypatch, httpx.MockTransport(llm))

    info = aig.write_script(PROMPT, 15.0, "professional", "youtube_shorts")
    assert len(llm.payloads) == 1
    assert info["title"] == "El tema en detalle"
    assert len(info["sentences"]) == 4
    assert len(info["queries"]) == 4


def test_ai_generate_write_script_fails_when_a_block_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un bloque ilegible tumba el job con un mensaje claro (no un guion de relleno)."""
    _llm_env(monkeypatch)
    state = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            body = {"title": "t", "hook": "h", "script": "Uno. Dos.", "queries": ["a", "b"]}
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(body)},
                                  "finish_reason": "stop"}]},
                request=request,
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": ""},
                                                      "finish_reason": "length"}]},
                              request=request)

    monkeypatch.setattr("app.ai_generate.time.sleep", lambda *_: None)
    _patch_httpx(monkeypatch, httpx.MockTransport(_handler))

    with pytest.raises(aig.ScriptGenerationError):
        aig.write_script(PROMPT, 360.0, "professional", "youtube")


def test_run_job_generate_fails_without_llm(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin guion el job queda `failed` con el motivo — no `done` con video de prueba."""
    storage = tmp_path / "storage"
    store = JobStore(storage)
    job = store.create_job(
        "IA sin LLM", source="generate", source_url=None, owner_id=user_id
    )
    _write_generate_meta(store, job.id, duration=15)
    monkeypatch.setattr("app.ai_generate.build_voiceover", lambda *a, **k: None)
    monkeypatch.setenv("EDGETAPE_LLM_BASE_URL", "")
    monkeypatch.setenv("EDGETAPE_LLM_MODEL", "")
    monkeypatch.setenv("EDGETAPE_GROQ_API_KEY", "")

    asyncio.run(run_job(job.id, store, MockTranscriber()))

    job = store.get_job(job.id)
    assert job is not None and job.status == "failed"
    assert job.error and "LLM" in job.error
    # no se generó un video de relleno
    assert not store.source_path(job.id).exists()


def test_ai_generate_size_for() -> None:
    assert _size_for("youtube") == (1920, 1080)
    assert _size_for("youtube_shorts") == (1080, 1920)
    assert _size_for("tiktok") == (1080, 1920)
    assert _size_for("instagram_reels") == (1080, 1920)


def test_ai_generate_durations_and_floor() -> None:
    assert 360 in aig.GENERATE_DURATIONS
    assert 900 in aig.GENERATE_DURATIONS
    assert aig.GENERATE_DURATIONS == sorted(aig.GENERATE_DURATIONS)
    assert aig.YOUTUBE_MIN_LONG == 360.0


def test_ai_generate_scene_images_offline(tmp_path: Path) -> None:
    """Con EDGETAPE_AI_IMAGES=0 no hay descargas: todas las escenas sin imagen."""
    sizes = aig._fetch_scene_images(["A B C D E"], (1080, 1920), tmp_path)
    assert sizes == [None]
    # escenas título/cierre nunca buscan imagen
    assert aig._fetch_scene_images(["a.", "b.", "c."], (1080, 1920), tmp_path) == [None, None, None]


def test_ai_generate_scene_media_offline(tmp_path: Path) -> None:
    """Sin red (EDGETAPE_AI_IMAGES=0) el b-roll queda vacío pero la estructura se mantiene."""
    assets = aig._fetch_scene_media(
        ["a.", "b.", "c."], ["one", "two", "three"], (1080, 1920), tmp_path
    )
    assert assets == [(None, False)] * 3


def test_broll_budget_covers_every_body_scene() -> None:
    """El techo de búsqueda debe alcanzar para TODAS las escenas del cuerpo.

    Regresión: con 2,5s por escena el techo se agotaba en la escena 22 de 57 y
    las 35 restantes salían en gradiente de marca (68% del video sin b-roll).
    """
    from app import ai_generate as a

    # 6 min: 57 escenas, 55 del cuerpo -> el presupuesto cubre las 55 a ~6s
    n57 = a._scene_count(360)
    budget = max(45.0, min(540.0, (n57 - 2) * a._BROLL_SECONDS_PER_SCENE))
    assert budget >= (n57 - 2) * 5.0, (n57, budget)
    # 15 min: el tope de escenas (90) no debe dejarnos sin presupuesto
    n90 = a._scene_count(900)
    budget90 = max(45.0, min(540.0, (n90 - 2) * a._BROLL_SECONDS_PER_SCENE))
    assert budget90 >= (n90 - 2) * 5.0, (n90, budget90)


def test_material_library_never_repeats(tmp_path: Path) -> None:
    """take() marca el material como usado: dos escenas nunca reciben el mismo b-roll."""
    from app import materials

    lib = materials.MaterialLibrary(pexels_keys=["k"], pixabay_keys=[])
    pool = [
        materials.Material(
            uid=f"u{i}", provider="pexels", kind="video", url=f"http://x/{i}.mp4",
            width=1920, height=1080, duration=10.0, landscape=True,
        )
        for i in range(3)
    ]
    picked = [lib.take(pool) for _ in range(4)]
    assert [m.uid for m in picked if m] == ["u0", "u1", "u2"]
    assert picked[-1] is None


def test_material_search_prioritizes_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """El b-roll manda: las fotos solo se piden si no hay video."""
    from app import materials

    lib = materials.MaterialLibrary(pexels_keys=["k"], pixabay_keys=[])
    calls: list[str] = []

    def _fake(_client, _query, kind, *args, **kwargs):
        calls.append(kind)
        return [
            materials.Material(
                uid=f"pexels-{kind}", provider="pexels", kind=kind,
                url="http://x/1", width=10, height=10, duration=1.0, landscape=True,
            )
        ]

    monkeypatch.setattr(lib, "_pexels", _fake)
    lib.search("city", True)
    assert calls == ["video"]


def test_pixabay_prefers_smallest_variant_that_clears_1080p() -> None:
    """Pixabay daba siempre `large` (~50MB) y el tope de 48MB la descartaba.

    Para un plano de 6-10s se elige la variante MÁS PEQUEÑA que aún dé 1080p.
    """
    from app import materials

    full = {
        "small": {"url": "s", "width": 1920, "height": 1080},
        "medium": {"url": "m", "width": 1920, "height": 1080},
        "large": {"url": "l", "width": 3840, "height": 2160},
    }
    assert materials._pick_video_variant(full)["url"] == "s"

    # `small` por debajo de 1080 no sirve: se sube a la mayor disponible
    too_small = {
        "small": {"url": "s", "width": 960, "height": 540},
        "large": {"url": "l", "width": 3840, "height": 2160},
    }
    assert materials._pick_video_variant(too_small)["url"] == "l"

    # ninguna llega a 1080: mejor la mayor que quedarse sin b-roll
    assert materials._pick_video_variant({"large": {"url": "l", "width": 1280, "height": 720}})["url"] == "l"
    assert materials._pick_video_variant({}) is None


def test_ai_generate_music_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La música es opt-in: 'none' no toca audio, un nombre válido sí se mezcla."""
    monkeypatch.setenv("EDGETAPE_MUSIC_DIR", str(tmp_path / "music"))
    assert aig._resolve_music("none") is None
    assert aig._resolve_music(None) is None
    assert aig.list_music_tracks() == []

    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "lofi.mp3").write_bytes(b"fake")
    (folder / "notes.txt").write_text("no es audio", encoding="utf-8")
    assert aig.list_music_tracks() == ["lofi.mp3"]
    assert aig._resolve_music("lofi") == folder / "lofi.mp3"
    assert aig._resolve_music("lofi.mp3") == folder / "lofi.mp3"
    assert aig._resolve_music("auto") in (folder / "lofi.mp3",)
    # pista inexistente → cae a la primera disponible (no rompe el render)
    assert aig._resolve_music("no-existe.mp3") == folder / "lofi.mp3"


def test_render_segment_video_loops_broll(tmp_path: Path) -> None:
    """Un b-roll más corto que la escena se loopea y se escala al formato destino."""
    src = tmp_path / "broll.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", str(src),
        ],
        check=True,
    )
    out = tmp_path / "seg.mp4"
    aig._render_segment_video(src, 4.0, 0, (1080, 1920), out)
    assert out.exists()
    assert _video_size(out) == (1080, 1920)
    assert 3.5 <= probe_duration(out) <= 4.5


def test_render_video_uses_broll_and_stills(tmp_path: Path) -> None:
    """render_video acepta mezcla de assets de video e imágenes (Ken Burns)."""
    src = tmp_path / "broll.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", str(src),
        ],
        check=True,
    )
    still = tmp_path / "still.png"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:size=1280x720:duration=1",
            "-frames:v", "1", str(still),
        ],
        check=True,
    )
    out = tmp_path / "out.mp4"
    aig.render_video(
        [src, still], [True, False], [None, None], None,
        [0.0, 2.5], [2.5, 5.0], (1280, 720), 5.0, out, workdir=tmp_path / "wd",
    )
    assert out.exists()
    assert _video_size(out) == (1280, 720)
    assert 4.5 <= probe_duration(out) <= 5.5


def test_generate_endpoint_accepts_music(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path)

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.processing.run_job", _noop)
    resp = client.post(
        "/api/generate",
        headers=auth_headers,
        json={"prompt": PROMPT, "duration": 15, "music": "auto"},
    )
    assert resp.status_code == 202
    store = JobStore(tmp_path / "storage")
    job = store.get_job(resp.json()["job_id"])
    meta = json.loads(
        (store.job_dir(job.id) / "generate_meta.json").read_text(encoding="utf-8")
    )
    assert meta["music"] == "auto"


def test_music_endpoint_lists_tracks(
    tmp_path: Path, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDGETAPE_MUSIC_DIR", str(tmp_path / "music"))
    client = _client(tmp_path)
    assert client.get("/api/music").status_code == 401
    assert client.get("/api/music", headers=auth_headers).json() == {"tracks": []}


def test_run_job_generate_records_warning(
    tmp_path: Path, user_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin material de red el job termina 'done' pero avisa que usó fondos de marca."""
    store, job_id, _ = _run_generate_job(tmp_path, user_id, monkeypatch)
    job = store.get_job(job_id)
    assert job is not None and job.status == "done"
    assert job.warning and "material" in job.warning
    # los temporales de render se limpian: el export vive en exports/
    job_dir = store.job_dir(job_id)
    assert not (job_dir / "ai_tmp").exists()
    assert list((job_dir / "exports").glob("*.mp4"))
    # ni los intermedios de composición se quedan en la raíz del job: miden
    # como el video final y antes ocupaban el doble de disco por job
    assert not list(job_dir.glob("_comp*.mp4"))
    assert not list(job_dir.glob("_concat.txt"))
