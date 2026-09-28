from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_db_dir = tempfile.mkdtemp(prefix="edgetape-test-db-")
# Fuerza SQLite ANTES de importar app: EDGETAPE_DATABASE_URL tiene prioridad sobre
# DATABASE_URL, así que se asigna directamente (no setdefault) para ganarle al .env.
os.environ["EDGETAPE_DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["DATABASE_URL"] = os.environ["EDGETAPE_DATABASE_URL"]
os.environ["EDGETAPE_JWT_SECRET"] = "edgetape-test-secret"
# jobs en segundo plano sin Redis: corre la tarea en un hilo local
os.environ.setdefault("EDGETAPE_ASYNC_BACKEND", "inproc")
# Desactivar Ollama en tests para que usen heurístico (rápido)
os.environ["EDGETAPE_OLLAMA_URL"] = "http://127.0.0.1:1"
# Desactivar LLM remoto (Groq/OpenAI) en tests para que usen heurístico
os.environ["EDGETAPE_LLM_API_KEY"] = ""
os.environ["EDGETAPE_LLM_BASE_URL"] = ""
os.environ["EDGETAPE_LLM_MODEL"] = ""
# Desactivar Groq (metadata/heurístico y transcripción) — nunca pegar a la API real
os.environ["EDGETAPE_GROQ_API_KEY"] = ""
# ── Aceleración de tests ─────────────────────────────────────────────
# Exports sin recorte vertical (boxblur 1080x1920 es el cuello de botella ~360s)
os.environ["EDGETAPE_EXPORT_MODE"] = "original"
# Sin pausas deliberadas: metadata y cola de publicación inmediatas
os.environ["EDGETAPE_METADATA_DELAY"] = "0"
os.environ["EDGETAPE_QUEUE_TASK_DELAY"] = "0"
# Sin imágenes por escena (Wikimedia) en tests: sin red, renders deterministas
os.environ["EDGETAPE_AI_IMAGES"] = "0"
# Sin probe de Ollama (evita timeouts de conexión ~2.5s por test)
os.environ["EDGETAPE_OLLAMA_PROBE"] = "0"
# Build_transcriber siempre devuelve el mock (evita cargar faster-whisper)
os.environ["EDGETAPE_MOCK_TRANSCRIBE"] = "1"
# Quotas desactivadas: sin límite diario ni delay entre subidas
os.environ["EDGETAPE_MIN_UPLOAD_DELAY"] = "0"
os.environ["EDGETAPE_MAX_UPLOADS_PER_DAY"] = "999"

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def auth_token() -> str:
    app = create_app(tempfile.mkdtemp(prefix="edgetape-test-store-"))
    client = TestClient(app)
    email = "test@edgetape.dev"
    password = "secret123"
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Tester"},
    )
    if resp.status_code == 409:
        resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="session")
def user_id(auth_headers: dict[str, str]) -> str:
    app = create_app(tempfile.mkdtemp(prefix="edgetape-test-store-"))
    client = TestClient(app)
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]
