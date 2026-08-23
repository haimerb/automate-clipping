"""Cola durable de tareas con Celery + Redis.

Los jobs de procesamiento (descarga → transcripción → scoring) y el auto-publish
se encolan aquí en lugar de correr como `asyncio.create_task` dentro del proceso
del servidor: sobreviven reinicios del worker gracias a acks_late y quedan
pendientes en Redis si no hay worker disponible.

Backend de ejecución controlado por `EDGETAPE_ASYNC_BACKEND`:
- "celery" (default en producción/dev con Redis): envía a la cola con .delay().
- cualquier otro valor (tests): corre la tarea en un hilo local sin broker.
"""
from __future__ import annotations

import asyncio
import os
import threading

from celery import Celery

from .llm_scorer import build_clip_selector
from .processing import run_job
from .storage import JobStore
from .transcriber import build_transcriber


def _broker_url() -> str:
    return os.environ.get("EDGETAPE_CELERY_BROKER", "redis://localhost:6379/0")


celery_app = Celery("edgetape", broker=_broker_url(), backend=_broker_url())
celery_app.conf.update(
    task_acks_late=True,  # el mensaje se confirma al terminar la tarea, no al recibirla
    task_reject_on_worker_lost=True,  # si el worker muere, la tarea vuelve a la cola
    task_track_started=True,
    result_expires=86400,
)


def _store(storage_root: str) -> JobStore:
    return JobStore(storage_root)


@celery_app.task(name="edgetape.process_job")
def process_job(job_id: str, storage_root: str) -> None:
    asyncio.run(run_job(job_id, _store(storage_root), build_transcriber(), build_clip_selector()))


@celery_app.task(name="edgetape.auto_publish_clip")
def auto_publish_clip(
    job_id: str, clip_id: str, storage_root: str,
    platform: str = "youtube_shorts", account: str | None = None,
) -> None:
    from . import publish as pubmod

    asyncio.run(pubmod.auto_publish_clip(_store(storage_root), job_id, clip_id, platform, account))


def _dispatch(task, *args: object) -> None:
    if os.environ.get("EDGETAPE_ASYNC_BACKEND") == "celery":
        task.delay(*args)
    else:
        threading.Thread(target=lambda: task.apply(args=args), daemon=True).start()


def enqueue_job(job_id: str, storage_root: str) -> None:
    _dispatch(process_job, job_id, storage_root)


def enqueue_auto_publish(
    job_id: str, clip_id: str, storage_root: str,
    platform: str = "youtube_shorts", account: str | None = None,
) -> None:
    _dispatch(auto_publish_clip, job_id, clip_id, storage_root, platform, account)
