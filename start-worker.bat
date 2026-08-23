@echo off
REM Inicia el worker de Celery para procesar jobs.
REM Ejecutar DESPUES de `docker compose up -d` y `uvicorn app.main:app --reload --app-dir backend`.
cd /d "%~dp0backend"
celery -A app.tasks worker --pool=solo --loglevel=info
