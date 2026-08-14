# edgetape — video/audio clipping automation

Plataforma que escanea grabaciones largas, detecta los pasajes más fuertes con IA y los
presenta como un carrete de clips listos para recortar, exportar y **monetizar** en tus redes.

## Funcionalidades

- **Cuentas de usuario**: registro/login (JWT), cada usuario tiene sus jobs, clips y publicaciones en Postgres para auth.
- **Dos fuentes de video**: subir un archivo o pegar una URL de YouTube (se descarga con yt-dlp y se procesa igual).
- **Clips automáticos** por transcripción + detección heurística o selector LLM, con **vista previa en video** del clip exportado.
- **Selección para publicar**: marca los clips que vas a subir y revisa la lista lista-para-publicar con su monetización.
- **Cuentas vinculadas**: registra tus canales/perfiles de YouTube, TikTok y Facebook para asociar cada publicación.
- **Panel de monetización** por plataforma (YouTube Shorts, TikTok, Facebook Reels, Instagram Reels, otras):
  registra vistas, me gusta, comentarios y ganancias de cada publicación, con un dashboard de totales por plataforma.

## Stack

- **Backend**: Python + FastAPI. Pipeline: (descarga yt-dlp opcional) → ffprobe → transcripción → detección de clips → corte con ffmpeg.
- **Frontend**: React + Vite + TypeScript + **Material UI (v9)** con tema propio de la identidad edgetape (azul `#1E3A8A`, amarillo marcador `#FFC647`, Hanken Grotesk + Fragment Mono), en español.
- **Transcripción**: `faster-whisper` si está instalado; en caso contrario cae a un *mock* determinístico para que todo el flujo funcione sin modelos.
- **Detección de clips** (selector, configurable):
  - **LLM** (por defecto si hay config): envío por ventanas de ~90 s a cualquier endpoint compatible con OpenAI (funciona con GPT, Ollama, vLLM…); el modelo elige los mejores momentos con título + frase gancho.
  - **Heurístico** (fallback automático): scoring por frecuencia inversa de documento + palabras gancho + densidad de habla, umbrales adaptativos; cada clip se abre en pasajes con señal semántica y se corta en pausas > 4 s.

## Estructura

```
backend/   FastAPI app (app/), tests (tests/), storage/ (datos de jobs)
web/       React + Vite + TS (src/)
design/    Maqueta estática de referencia (design/mockup.html)
```

## Requisitos

- Python ≥ 3.10
- Node ≥ 18 (probado con 20)
- ffmpeg + ffprobe en el PATH
- Docker (para el Postgres de usuarios/auth)
- (opcional) yt-dlp viene en `requirements.txt` para la fuente YouTube

## Instalación

```bash
# Postgres (usuarios y cuentas; la API no arranca sin él)
docker compose up -d

# Backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r backend\requirements.txt

# Transcripción real (opcional, pesado)
pip install -r backend\requirements-ai.txt

# Frontend
cd web && npm install && cd ..
```

## Ejecutar

```bash
# Postgres (si aún no está arriba)
docker compose up -d

# Backend (API en http://localhost:8000, docs en /docs)
uvicorn app.main:app --reload --app-dir backend

# Frontend dev (en http://localhost:5173, proxya /api al 8000)
cd web && npm run dev
```

Para servir el frontend construido desde el propio backend: `cd web && npm run build`
(uvicorn sirve `web/dist` automáticamente en `/`).

## Test

```bash
cd backend && python -m pytest
cd web && npm run build        # typecheck (tsc) + bundle
```

`backend/tests/test_pipeline.py` genera un video sintético con ffmpeg y prueba el flujo
completo (upload → detección → export → descarga). Se omite si ffmpeg no está en el PATH.

## API

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/auth/register` | Crea usuario (`email`, `password`, `name`); devuelve `access_token` + `user` |
| POST | `/api/auth/login` | Inicia sesión; devuelve token |
| GET | `/api/auth/me` | Usuario actual (Bearer token) |
| GET | `/api/accounts` | Cuentas vinculadas del usuario |
| POST | `/api/accounts` | Vincula una cuenta (`platform`, `name`, `handle`, `token?`) |
| PATCH | `/api/accounts/{id}` | Actualiza una cuenta |
| DELETE | `/api/accounts/{id}` | Desvincula una cuenta |
| POST | `/api/jobs` | Sube media (multipart `file`), crea job 202, procesa en background |
| POST | `/api/jobs/youtube` | Crea job desde URL de YouTube (`{"url": "..."}`); valida el dominio |
| GET | `/api/jobs/{id}` | Estado del job (`queued/downloading/processing/done/failed` + `progress`) |
| GET | `/api/jobs/{id}/clips` | Clips detectados |
| PATCH | `/api/jobs/{id}/clips/{cid}` | Marca/desmarca clip para publicar (`{"publish": bool}`) |
| POST | `/api/jobs/{id}/clips/{cid}/export` | Corta el clip con ffmpeg |
| GET | `/api/jobs/{id}/clips/{cid}/download` | Descarga el clip exportado |
| GET | `/api/jobs/{id}/clips/{cid}/preview` | Sirve el mp4 exportado para `<video>` (soporta Range) |
| GET | `/api/jobs/{id}/platforms` | Publicaciones de plataformas del job |
| POST | `/api/jobs/{id}/clips/{cid}/platforms` | Registra publicación de un clip (`account` opcional) |
| PATCH | `/api/jobs/{id}/platforms/{pid}` | Actualiza una publicación |
| DELETE | `/api/jobs/{id}/platforms/{pid}` | Elimina una publicación |
| GET | `/api/dashboard` | Agregados del usuario: ganancias/vistas totales y por plataforma + cuentas + últimas publicaciones |
| GET | `/api/health` | Estado, transcriber, scorer y disponibilidad de yt-dlp |

Todos los endpoints de jobs/posts/dashboard/cuentas exigen `Authorization: Bearer <token>`.
Los jobs se persisten como JSON bajo `backend/storage/{job_id}/` (job.json, clips.json, posts.json),
scoped por usuario; los usuarios y cuentas vinculadas viven en PostgreSQL.

## Configuración por entorno

| Variable | Efecto |
|---|---|
| `EDGETAPE_DATABASE_URL` | URL de Postgres (default `postgresql+psycopg2://edgetape:edgetape@localhost:5432/edgetape`; `DATABASE_URL` también funciona) |
| `EDGETAPE_JWT_SECRET` | Secreto para firmar los JWT de sesión (12 h) |
| `EDGETAPE_MOCK_TRANSCRIBE=1` | Fuerza transcripción mock |
| `WHISPER_MODEL` | Tamaño del modelo whisper (default `base`) |
| `EDGETAPE_STORAGE` | Raíz de almacenamiento (default `backend/storage`) |
| `EDGETAPE_LLM_MODEL` | Modelo del selector LLM (default `gpt-4o-mini`) |
| `EDGETAPE_LLM_BASE_URL` | Endpoint compatible con OpenAI (default `https://api.openai.com/v1`). Para Ollama local: `http://localhost:11434/v1` |
| `EDGETAPE_LLM_API_KEY` | API key; se omite `Authorization` si está vacía (útil para modelos locales) |
| `EDGETAPE_YT_COOKIES` | Ruta a un archivo de cookies (formato Netscape) para descargar videos de YouTube que requieren sesión o ante bloqueos (403) persistentes |

El selector LLM se activa si existe cualquiera de las variables `EDGETAPE_LLM_*`. Si el modelo falla o no hay config, el pipeline cae al heurístico automáticamente. El job expone qué selector se usó en `job.scorer`.

> **Nota YouTube (HTTP 403)**: si la descarga falla con `HTTP Error 403: Forbidden`, actualiza yt-dlp
> (`pip install -U yt-dlp`). La descarga ya reintenta con distintos "player clients" de YouTube y usa
> User-Agent de navegador. Para casos persistentes, exporta tus cookies de YouTube a un archivo
> Netscape (p. ej. con una extensión de cookies) y apúntalo con `EDGETAPE_YT_COOKIES`.

## Próximos pasos / extensiones naturales

- Conexión real con APIs de YouTube Analytics / TikTok / Meta para importar vistas y ganancias automáticamente (requiere OAuth y aprobación por plataforma).
- Publicación automática de clips desde la plataforma (subir el mp4 exportado a las cuentas vinculadas).
- Características acústicas (energía/risas) vía ffmpeg como señal adicional de momento fuerte.
- Ajuste manual de in/out en el frontend antes de exportar.
- Recorte sin recodificación (`-c copy`) cuando el usuario priorice velocidad.
