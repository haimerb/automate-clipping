"""Re-render de jobs `generate` con el motor actual + limpieza de disco."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import JobStore
from app.transcriber import MockTranscriber


@pytest.fixture()
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "storage")


def _client(store: JobStore) -> TestClient:
    return TestClient(create_app(store.root, MockTranscriber()))


def _registered(client: TestClient) -> dict[str, str]:
    import uuid

    resp = client.post(
        "/api/auth/register",
        json={
            "email": f"regen-{uuid.uuid4().hex[:10]}@example.com",
            "password": "secreto1234",
            "name": "Ana",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _generate_job(store: JobStore, owner_id: str, **meta_extra):
    job = store.create_job("IA: cafe", source="generate", owner_id=owner_id)
    job_dir = store.job_dir(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "prompt": "un cafe de especialidad",
        "duration": 30,
        "style": "professional",
        "platform": "youtube_shorts",
        "voice": "es_mx_female",
        "music": "none",
        "script_gen": {"script": "guion viejo", "hook": "h", "warnings": ["viejo"]},
        **meta_extra,
    }
    (job_dir / "generate_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (job_dir / "source").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 2048)
    job.status = "done"
    job.progress = 100
    job.duration = 30.0
    store.save_job(job)
    return job


def _meta(job_dir: Path) -> dict:
    return json.loads((job_dir / "generate_meta.json").read_text(encoding="utf-8"))


# ── Regenerate ─────────────────────────────────────────────────


def test_regenerate_archives_source_and_requeues(store: JobStore, monkeypatch):
    monkeypatch.setenv("EDGETAPE_ASYNC_BACKEND", "celery")
    sent: list[tuple] = []
    monkeypatch.setattr(
        "app.main.enqueue_job", lambda jid, root: sent.append((jid, root)) or None
    )
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])

    resp = client.post(f"/api/jobs/{job.id}/regenerate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert sent and sent[0][0] == job.id

    # el source viejo quedó archivado y el pipeline lo va a recrear
    assert not (store.job_dir(job.id) / "source").exists()
    assert list((store.job_dir(job.id) / "previous").iterdir())

    fresh = store.get_job(job.id)
    assert fresh.status == "queued"
    assert fresh.progress == 0
    assert fresh.warning is None


def test_regenerate_resets_script_gen_and_applies_overrides(store: JobStore, monkeypatch):
    monkeypatch.setenv("EDGETAPE_ASYNC_BACKEND", "celery")
    monkeypatch.setattr("app.main.enqueue_job", lambda jid, root: None)
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])

    resp = client.post(
        f"/api/jobs/{job.id}/regenerate",
        json={"music": "ambient-pad", "style": "cinematic", "duration": 60},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    meta = _meta(store.job_dir(job.id))
    assert meta["music"] == "ambient-pad"
    assert meta["style"] == "cinematic"
    assert meta["duration"] == 60
    assert "script_gen" not in meta  # el motor escribe uno nuevo
    assert meta["prompt"] == "un cafe de especialidad"


def test_regenerate_rejects_bad_duration(store: JobStore, monkeypatch):
    monkeypatch.setenv("EDGETAPE_ASYNC_BACKEND", "celery")
    monkeypatch.setattr("app.main.enqueue_job", lambda jid, root: None)
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])

    resp = client.post(
        f"/api/jobs/{job.id}/regenerate", json={"duration": 7}, headers=headers
    )
    assert resp.status_code == 422
    assert "duración inválida" in resp.json()["detail"]
    assert store.get_job(job.id).status == "done"  # no se tocó nada


def test_regenerate_rejects_upload_jobs(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = store.create_job("charla.mp4", source="upload", owner_id=me["id"])
    job.status = "done"
    store.save_job(job)

    resp = client.post(f"/api/jobs/{job.id}/regenerate", json={}, headers=headers)
    assert resp.status_code == 409
    assert "generados con IA" in resp.json()["detail"]


def test_regenerate_rejects_running_job(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])
    job.status = "processing"
    store.save_job(job)

    resp = client.post(f"/api/jobs/{job.id}/regenerate", json={}, headers=headers)
    assert resp.status_code == 409
    assert "procesando" in resp.json()["detail"]


def test_regenerate_requires_owner(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    job = _generate_job(store, "otro-usuario")
    resp = client.post(f"/api/jobs/{job.id}/regenerate", json={}, headers=headers)
    assert resp.status_code == 404


# ── Purga de media ─────────────────────────────────────────────


def test_delete_media_keeps_metadata(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])
    exports = store.exports_dir(job.id)
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "clip.mp4").write_bytes(b"0" * 4096)
    (store.job_dir(job.id) / "previous").mkdir(parents=True, exist_ok=True)
    (store.job_dir(job.id) / "previous" / "source_1.mp4").write_bytes(b"0" * 2048)

    resp = client.request("DELETE", f"/api/jobs/{job.id}/media", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["freed_bytes"] >= 6144

    assert not (store.job_dir(job.id) / "source").exists()
    assert not (store.job_dir(job.id) / "previous").exists()
    assert not exports.exists()
    # siguen intactos
    assert (store.job_dir(job.id) / "job.json").exists()
    assert (store.job_dir(job.id) / "generate_meta.json").exists()
    assert any(j.id == job.id for j in store.list_jobs(me["id"]))

    # y se puede volver a renderizar
    assert (store.job_dir(job.id) / "generate_meta.json").exists()


def test_delete_media_rejects_running_job(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    me = client.get("/api/auth/me", headers=headers).json()
    job = _generate_job(store, me["id"])
    job.status = "exporting"
    store.save_job(job)
    resp = client.request("DELETE", f"/api/jobs/{job.id}/media", headers=headers)
    assert resp.status_code == 409


def test_delete_media_requires_owner(store: JobStore):
    client = _client(store)
    headers = _registered(client)
    job = _generate_job(store, "otro-usuario")
    resp = client.request("DELETE", f"/api/jobs/{job.id}/media", headers=headers)
    assert resp.status_code == 404


# ── Sweep ──────────────────────────────────────────────────────


def test_sweep_keeps_recent_and_latest_versions(tmp_path: Path, monkeypatch):
    store = JobStore(tmp_path / "storage")
    archive = store.archive_dir("job1")
    archive.mkdir(parents=True, exist_ok=True)
    for n in (1, 2, 3):
        (archive / f"source_{n}.mp4").write_bytes(b"0" * 1024)
    old = archive / "source_1.mp4"
    # sólo la versión 1 es antigua: el sweep la borra, la 3 (última) se conserva
    import os
    import time

    stale = time.time() - 40 * 86400
    os.utime(old, (stale, stale))
    os.utime(archive / "source_2.mp4", (stale, stale))

    result = store.sweep_media(max_age_days=30, keep=1)
    assert result["files"] == 2  # source_1 y source_2 (viejas y fuera del keep)
    assert not old.exists()
    assert not (archive / "source_2.mp4").exists()
    assert (archive / "source_3.mp4").exists()  # la última versión nunca se toca


def test_sweep_removes_orphan_ai_tmp(tmp_path: Path):
    store = JobStore(tmp_path / "storage")
    orphan = store.root / "job-huerfano"
    (orphan / "ai_tmp").mkdir(parents=True, exist_ok=True)
    (orphan / "ai_tmp" / "scene_1.asset").write_bytes(b"0" * 2048)
    live_job = store.create_job("vivo.mp4", source="upload")
    live = store.job_dir(live_job.id)
    (live / "ai_tmp").mkdir(parents=True, exist_ok=True)
    (live / "ai_tmp" / "scene_0.asset").write_bytes(b"0" * 2048)

    result = store.sweep_media(max_age_days=7)
    assert result["files"] == 1
    assert not (orphan / "ai_tmp").exists()
    assert (live / "ai_tmp" / "scene_0.asset").exists()


def test_archive_source_returns_none_when_missing(store: JobStore):
    assert store.archive_source("no-existe") is None


# ── CLI de limpieza ────────────────────────────────────────────


def test_cleanup_cli_sweeps(tmp_path: Path, monkeypatch, capsys):
    from app import cleanup

    store = JobStore(tmp_path / "storage")
    archive = store.archive_dir("j1")
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "source_1.mp4").write_bytes(b"0" * 1024)
    orphan = store.root / "j2"
    (orphan / "ai_tmp").mkdir(parents=True, exist_ok=True)
    (orphan / "ai_tmp" / "scene_0.asset").write_bytes(b"0" * 1024)

    monkeypatch.setattr(
        cleanup.argparse.ArgumentParser, "parse_args", lambda self: _args(str(store.root))
    )
    assert cleanup.main() == 0
    out = capsys.readouterr().out
    assert "2 archivos" in out
    assert not archive.exists()
    assert not (orphan / "ai_tmp").exists()


def test_sweep_media_previous_respeta_keep_y_edad(tmp_path: Path):
    store = JobStore(tmp_path / "storage")
    archive = store.archive_dir("j1")
    archive.mkdir(parents=True, exist_ok=True)
    antiguo = archive / "source_1.mp4"
    antiguo.write_bytes(b"0" * 1024)
    reciente = archive / "source_2.mp4"
    reciente.write_bytes(b"0" * 1024)
    hace_diez_dias = time.time() - 10 * 86400
    os.utime(antiguo, (hace_diez_dias, hace_diez_dias))

    # keep=1 + days=7 → sobrevive el más nuevo, se va el antiguo
    res = store.sweep_media(max_age_days=7.0, keep=1)
    assert res["files"] == 1
    assert reciente.exists() and not antiguo.exists()

    # days=0 → borra lo que exceda keep sin mirar la edad (antes fallaba si
    # el mtime quedaba por encima de `now` por precisión del sistema de archivos)
    res = store.sweep_media(max_age_days=0.0, keep=0)
    assert res["files"] == 1
    assert not reciente.exists()


def test_cleanup_cli_purges_one_job(tmp_path: Path, monkeypatch, capsys):
    from app import cleanup

    store = JobStore(tmp_path / "storage")
    job = store.create_job("cafe.mp4", source="upload")
    (store.source_path(job.id)).write_bytes(b"0" * 4096)
    monkeypatch.setattr(
        cleanup.argparse.ArgumentParser, "parse_args", lambda self: _args(str(store.root), job=job.id)
    )
    assert cleanup.main() == 0
    assert "liberados" in capsys.readouterr().out
    assert not store.source_path(job.id).exists()


def test_cleanup_cli_unknown_job(tmp_path: Path, monkeypatch):
    from app import cleanup

    store = JobStore(tmp_path / "storage")
    monkeypatch.setattr(
        cleanup.argparse.ArgumentParser, "parse_args", lambda self: _args(str(store.root), job="nope")
    )
    assert cleanup.main() == 1


def _args(storage: str, job: str | None = None):
    import argparse

    ns = argparse.Namespace(storage=storage, days=0.0, keep=0, job=job)
    return ns


# ── Storage misconfigurado ────────────────────────────────────


def test_relative_storage_fails_fast(monkeypatch):
    """Una ruta relativa (o de otro SO) debe reventar al arrancar, no en cada job."""
    from app.main import _resolve_storage

    monkeypatch.delenv("EDGETAPE_STORAGE", raising=False)
    with pytest.raises(RuntimeError, match="ruta absoluta"):
        _resolve_storage("storage/relativo")


def test_windows_path_in_linux_fails_fast(monkeypatch):
    from app.main import _resolve_storage

    monkeypatch.setenv("EDGETAPE_STORAGE", "C:/Users/algo/storage")
    try:
        import os

        relative_on_this_os = not os.path.isabs("C:/Users/algo/storage")
    except Exception:  # pragma: no cover
        relative_on_this_os = True
    if not relative_on_this_os:
        pytest.skip("en Windows esa ruta sí es válida")
    with pytest.raises(RuntimeError, match="ruta absoluta"):
        _resolve_storage(None)


def test_absolute_storage_is_accepted(tmp_path: Path):
    from app.main import _resolve_storage

    store = _resolve_storage(tmp_path / "storage")
    assert store.root.is_absolute()
    assert store.root.exists()
