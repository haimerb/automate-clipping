#!/usr/bin/env bash
# Inicia el worker de Celery para procesar jobs.
# Ejecutar DESPUES de `docker compose up -d` y `uvicorn app.main:app --reload --app-dir backend`.
cd "$(dirname "$0")/backend"
celery -A app.tasks worker --pool=solo --loglevel=info
