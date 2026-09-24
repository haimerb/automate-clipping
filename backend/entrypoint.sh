#!/bin/sh
set -e

ROLE="${EDGETAPE_ROLE:-all}"
PORT="${PORT:-8000}"

echo "[entrypoint] role=${ROLE} port=${PORT}"

start_worker() {
  echo "[entrypoint] lanzando celery worker..."
  celery -A app.tasks worker --pool=solo --loglevel=info &
  CELERY_PID=$!
  echo "[entrypoint] celery worker pid=${CELERY_PID}"
}

start_api() {
  echo "[entrypoint] lanzando API (uvicorn) en el puerto ${PORT}..."
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
}

case "$ROLE" in
  api)
    start_api
    ;;
  worker)
    start_worker
    wait "$CELERY_PID"
    ;;
  all)
    # La API queda en primer plano; si muere, Docker reinicia el contenedor
    # (restart: unless-stopped) y con ello también el worker.
    start_worker
    trap 'kill "$CELERY_PID" 2>/dev/null || true' TERM INT EXIT
    start_api
    ;;
  *)
    echo "[entrypoint] EDGETAPE_ROLE inválido: ${ROLE} (api | worker | all)"
    exit 1
    ;;
esac