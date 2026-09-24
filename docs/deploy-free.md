# Deploy gratuito de edgetape

Guía para publicar el proyecto **sin gastar nada**. Dos caminos viables según tu objetivo:

1. **Demo pública (recomendado):** Hugging Face Spaces (Docker) + Neon (Postgres) + Upstash (Redis). Sin tarjeta.
2. **Uso continuo/robusto:** un VPS pequeño (p. ej. Oracle Always Free, aunque pide tarjeta al registrar).

## Sobre el límite de YouTube (`uploadLimitExceeded`)

Antes de desplegar, ten claro lo siguiente (aplica igual en local o en el hosting):

- `uploadLimitExceeded` (HTTP 400) es el **límite diario del CANAL de YouTube**, no del
  proyecto de la API ni del servidor. Google lo documenta como restricción de la plataforma,
  separada de tu cuota de API (100 `videos.insert`/día por proyecto).
- Se comparte entre la web, la app móvil y la API. La única salida es **esperar 24 h**.
- El backend ya lo gestiona desde 2026-09:
  - `EDGETAPE_MAX_UPLOADS_PER_DAY` (default 6) frena las subidas por canal por día.
  - `EDGETAPE_MIN_UPLOAD_DELAY` (default 600 s) separa subidas del mismo canal.
  - Al recibir `uploadLimitExceeded`, la cuenta se **pausa 24 h** y el clip pasa a
    `status="listo"` con `method="manual"` (enlace a YouTube Studio) y el motivo en `post.error`.
- Canales **nuevos** se topan antes (~10-20/día); la verificación del canal en YouTube aumenta
  el tope. Los proyectos de API **sin verificar** (post 28-jul-2020) fuerzan los videos a privado.

## Stack a desplegar

- API FastAPI + worker Celery (mismo contenedor con `EDGETAPE_ROLE=all`).
- Postgres → **Neon** (0.5 GB gratis, sin tarjeta).
- Redis (broker de Celery) → **Upstash** (256 MB, 500k cmd/mes, sin tarjeta).
- Frontend React: ya lo sirve FastAPI desde `web/dist` (se compila en el Dockerfile multi-etapa).
- ffmpeg: instalado en la imagen (clips verticales).

## Requisitos previos

1. Crear proyecto en [Neon](https://neon.tech) y copiar la URL de conexión
   (formato `postgresql://user:pass@host/db` — la app espera `postgresql+psycopg2://...`, se ajusta abajo).
2. Crear base de datos en [Upstash](https://upstash.com) → Redis → copiar `UPSTASH_REDIS_REST_URL`
   (formato REST) y la URL del broker `redis://default:pass@host:port`.
3. Variables del `.env`:
   ```
   EDGETAPE_DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST/dbname
   EDGETAPE_JWT_SECRET=<secreto largo, ver .env.example>
   EDGETAPE_CELERY_BROKER=redis://default:TOKEN@HOST:PORT
   EDGETAPE_ASYNC_BACKEND=celery
   EDGETAPE_YT_CLIENT_ID=
   EDGETAPE_YT_CLIENT_SECRET=
   EDGETAPE_YT_REDIRECT_URI=https://TU-USUARIO-APP.hf.space/api/youtube/callback
   ```

## Opción 1 — Hugging Face Spaces (Docker, sin tarjeta)

Un Space **Docker** corre un solo contenedor → usa `EDGETAPE_ROLE=all` (API + worker juntos).

1. Crea un Space en <https://huggingface.co/new-space> → SDK **Docker** (Boje: pesado; mínimo).
2. Push del repo al Space (es un repo git aparte, como el proyecto):
   ```bash
   git remote add space https://huggingface.co/spaces/TU-USUARIO/TU-SPACE
   git push space main
   ```
3. En **Settings → Variables and secrets** añade las vars del `.env` (todas excepto
   `EDGETAPE_CELERY_BROKER`/`EDGETAPE_DATABASE_URL` se leen también de `.env`, pero mejor por secrets).
4. El Space levanta la imagen (build multi-etapa: node → python) y expone el puerto
   `7860` por defecto (la imagen expone `8000`; el entrypoint usa `$PORT`, que HF define a 7860).

### Comprobación

- URL pública: `https://TU-USUARIO-TU-SPACE.hf.space` → sirve login + frontend.
- OAuth de YouTube: el `redirect_uri` debe coincidir con esa URL (`/api/youtube/callback`).
- El log del Space muestra `role=all` y ambos procesos.

### Limitaciones de Spaces free

- El Space **se duerme** tras ~48 h sin tráfico (la máquina virtual de la CPU free).
- Disco efímero en rebuild (los jobs/videos se pierden al reconstruir). Para persistir:
  copiar `backend/storage/` a un bucket (p. ej. Cloudflare R2 vía S3).
- CPU compartida: un clip grande tarda más que en local.

## Opción 2 — VPS pequeño (uso continuo)

Si necesitas 24/7 sin sleep, usa un VPS con Docker (p. ej. Oracle Always Free ARM 4 vCPU/24 GB,
o el plan gratuito de otro proveedor):

1. `git clone` + `.env` completo (con `EDGETAPE_CELERY_BROKER=redis://redis:6379/0` y
   `EDGETAPE_DATABASE_URL=postgresql+psycopg2://edgetape:edgetape@db:5432/edgetape` de compose).
2. `docker compose up -d --build` → arranca `db` + `redis` + `api` + `worker`.
3. Exponer el puerto 8000 (o poner nginx/Cloudflare Tunnel delante).

## Notas del Dockerfile

- Contexto de build: **raíz del repo** (`docker build -f backend/Dockerfile .`).
- `EDGETAPE_ROLE` controla qué arranca el entrypoint:
  - `api` → solo uvicorn (servicio `api` de compose).
  - `worker` → solo Celery (servicio `worker` de compose).
  - `all` → uvicorn en primer plano + worker en background (HF Spaces).
- La compilación del frontend (`pnpm build` → `web/dist`) ocurre en la etapa `web`.