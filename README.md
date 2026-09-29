# edgetape — video/audio clipping automation

Plataforma que escanea grabaciones largas, detecta los pasajes más fuertes con IA y los
presenta como un carrete de clips listos para recortar, exportar y **monetizar** en tus redes.

## Funcionalidades

- **Cuentas de usuario**: registro/login (JWT), cada usuario tiene sus jobs, clips y publicaciones en Postgres para auth.
- **Tres fuentes de video**: subir un archivo, pegar una URL (YouTube o cualquier http/https resoluble con yt-dlp) o **generar el video con IA**.
- **Generador con IA** (`/api/generate`): guion (LLM o fallback), voz edge-tts/gTTS en español, **b-roll real de Pexels/Pixabay** por escena, subtítulos quemados y música de fondo seleccionable. Nunca falla en silencio: cada degradación se avisa en el job.
- **Clips automáticos** por transcripción + detección heurística o selector LLM, con **vista previa en video** del clip exportado.
- **Selección para publicar**: marca los clips que vas a subir y revisa la lista lista-para-publicar con su monetización.
- **Cuentas vinculadas con OAuth real**: YouTube, TikTok, Facebook e Instagram (botón *Conectar*; en TikTok/Meta se detectan páginas e IG business automáticamente).
- **Publicación automática**: sube clips a YouTube/TikTok/Facebook/Instagram en paralelo, con reintentos por cuenta, cola persistente y respaldo a Studio.
- **Edición de metadata**: edita título, descripción y tags de cada clip antes de publicar.
- **Múltiples miniaturas**: genera 5 opciones por clip y selecciona la mejor antes de publicar.
- **Destinos persistentes**: guarda qué plataforma/cuenta usaste para cada clip, sin depender de localStorage.
- **Regenerar y liberar disco**: vuelve a renderizar un job generado con IA con el motor actual, o borra el video y los exports de un job que ya publicaste.
- **Panel de monetización** por plataforma (YouTube Shorts, TikTok, Facebook Reels, Instagram Reels, otras):
  registra vistas, me gusta, comentarios y ganancias de cada publicación, con un dashboard de totales por plataforma.

## Stack

- **Backend**: Python + FastAPI. Pipeline: (descarga yt-dlp opcional) → ffprobe → transcripción → detección de clips → corte con ffmpeg.
- **Frontend**: React + Vite + TypeScript + **Material UI (v9)** con tema propio de la identidad edgetape (azul `#1E3A8A`, amarillo marcador `#FFC647`, Hanken Grotesk + Fragment Mono), en español.
- **Transcripción**: Groq Whisper (`whisper-large-v3-turbo`) → `faster-whisper` local → mock determinístico.
- **Metadata viral**: Groq LLM (`gpt-oss-20b`) → API compatible → Ollama local → heurístico.
- **Detección de clips** (selector, configurable):
  - **LLM** (por defecto si hay config): envío por ventanas de ~90 s a cualquier endpoint compatible con OpenAI (funciona con GPT, Ollama, vLLM…); el modelo elige los mejores momentos con título + frase gancho.
  - **Heurístico** (fallback automático): scoring por frecuencia inversa de documento + palabras gancho + densidad de habla, umbrales adaptativos; cada clip se abre en pasajes con señal semántica y se corta en pausas > 4 s.
- **Colab (opcional)**: notebook `colab/edgetape_whisper.ipynb` para transcripción con GPU, conecta vía API al backend.

### Motor de video generado con IA

Cada job `source=generate` sigue esta cascada, y **cada salto queda registrado en `job.warning`**:

| Capa | Qué usa | Requiere |
|---|---|---|
| Guion | LLM (`EDGETAPE_LLM_*` / Groq / Ollama) → heurístico determinístico | nada |
| Voz | edge-tts → gTTS → sin voz | internet para TTS |
| Escenas | b-roll de Pexels/Pixabay (video > foto) | claves de stock (gratis) |
| | material generado por IA (`videogen.py`, de pago) | `EDGETAPE_VIDEOGEN_*` |
| | fotos de Wikimedia → fondos de marca | nada |
| Música | `backend/assets/music/*.mp3`, la elige el usuario | pistas en el repo |

- **Stock**: `materials.py` busca video antes que foto, deduplica por `uid` entre proveedores y escenas, y limita cada asset a 48 MB. El LLM escribe una query visual en inglés por escena; sin LLM se derivan palabras clave del guion.
- **Proveedor IA** (`videogen.py`): modo `image` (`POST {base}/images/generations`, OpenAI-compatible) o `webhook` (`POST` esperando `{"video_url": ...}`). Va **después** del stock y acotado a `EDGETAPE_VIDEOGEN_MAX_SCENES` escenas (1 por defecto) para no quemar cuota.
- **Video local por difusión**: no es una opción (una RTX 2060 de 6 GB no alcanza); por eso es un adaptador a proveedores remotos.
- **Regenerar**: `POST /api/jobs/{id}/regenerate` vuelve a renderizar un job antiguo con el motor actual; el video anterior se archiva en `previous/` y `python -m app.cleanup` lo recoge a los pocos días.

## Estructura

```
backend/    FastAPI app (app/), tests (tests/), storage/ (datos de jobs)
web/        React + Vite + TS (src/)
colab/      Notebooks para transcripción con GPU (Whisper)
design/     Maqueta estática de referencia (design/mockup.html)
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

# Frontend (pnpm, no npm)
cd web && pnpm install && cd ..
```

## Ejecutar

```bash
# Postgres (si aún no está arriba)
docker compose up -d

# Backend (API en http://localhost:8000, docs en /docs)
uvicorn app.main:app --reload --app-dir backend

# Frontend dev (en http://localhost:5173, proxya /api al 8000)
cd web && pnpm dev
```

Para servir el frontend construido desde el propio backend: `cd web && pnpm build`
(uvicorn sirve `web/dist` automáticamente en `/`).

## Test

```bash
cd backend && python -m pytest
cd web && pnpm build          # typecheck (tsc) + bundle
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
| POST | `/api/jobs/url` | Crea job desde cualquier URL descargable (http/https) |
| POST | `/api/generate` | Crea un job de video generado con IA (`prompt`, `duration`, `style?`, `platform?`, `voice?`, `music?`, `auto_publish?`, `account_id?`) |
| GET | `/api/music` | Pistas de música de fondo disponibles |
| GET | `/api/jobs/{id}` | Estado del job (`queued/downloading/processing/done/failed` + `progress`) |
| GET | `/api/jobs/{id}/clips` | Clips detectados |
| PATCH | `/api/jobs/{id}/clips/{cid}` | Marca/desmarca clip para publicar (`{"publish": bool}`) |
| PATCH | `/api/jobs/{id}/clips/{cid}/metadata` | Actualiza título, descripción y tags de un clip |
| GET | `/api/jobs/{id}/clips/{cid}/thumbs` | Genera 5 miniaturas del clip (10%-90%) |
| PATCH | `/api/jobs/{id}/clips/{cid}/thumbnail` | Selecciona miniatura (`{"index": 0-4}`) |
| POST | `/api/jobs/{id}/clips/{cid}/export` | Corta el clip con ffmpeg |
| GET | `/api/jobs/{id}/clips/{cid}/download` | Descarga el clip exportado |
| GET | `/api/jobs/{id}/clips/{cid}/preview` | Sirve el mp4 exportado para `<video>` (soporta Range) |
| POST | `/api/jobs/{id}/clips/{cid}/publish` | Publica clip en plataformas vinculadas (paralelo, con respaldo Studio) |
| GET | `/api/jobs/{id}/platforms` | Publicaciones de plataformas del job |
| POST | `/api/jobs/{id}/clips/{cid}/platforms` | Registra publicación de un clip (`account` opcional) |
| PATCH | `/api/jobs/{id}/platforms/{pid}` | Actualiza una publicación |
| DELETE | `/api/jobs/{id}/platforms/{pid}` | Elimina una publicación |
| POST | `/api/jobs/{id}/reprocess` | Regenera metadata viral de clips existentes |
| POST | `/api/jobs/{id}/regenerate` | Vuelve a renderizar un job `generate` con el motor actual (overrides opcionales `music/style/voice/duration`) |
| DELETE | `/api/jobs/{id}/media` | Borra fuente, exports y versiones previas; conserva job, clips y posts |
| GET | `/api/accounts/{id}/tiktok/auth` | URL de OAuth de TikTok (Content Posting API) |
| GET | `/api/tiktok/callback` | Callback de TikTok: guarda el `refresh_token` de la cuenta |
| GET | `/api/accounts/{id}/meta/auth` | URL de Facebook Login (páginas + IG business) |
| GET | `/api/meta/callback` | Callback de Meta: guarda el Page Access Token y detecta la página o la IG |
| GET | `/api/public/clips/{job}/{clip}/{token}.mp4` | Clip con URL firmada (lo que descarga Meta para publicar un Reel; sin Bearer) |
| POST | `/api/jobs/{id}/transcription` | Recibe transcripción desde Colab (requiere `EDGETAPE_COLAB_SECRET`) |
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
| `EDGETAPE_LLM_MODEL` | Modelo del selector LLM y metadata (default `gpt-4o-mini`) |
| `EDGETAPE_LLM_BASE_URL` | Endpoint compatible con OpenAI (default `https://api.openai.com/v1`). Para Groq: `https://api.groq.com/openai/v1` |
| `EDGETAPE_LLM_API_KEY` | API key; se omite `Authorization` si está vacía (útil para modelos locales) |
| `EDGETAPE_GROQ_API_KEY` | API key de Groq (gratis) para metadata viral con `openai/gpt-oss-20b` y transcripción con `whisper-large-v3-turbo` |
| `EDGETAPE_OLLAMA_URL` | URL de Ollama local (default `http://localhost:11434`); detecta modelos disponibles automáticamente |
| `EDGETAPE_COLAB_SECRET` | Secreto para autenticar el endpoint de transcripción desde Colab |
| `EDGETAPE_YT_COOKIES` | Ruta a un archivo de cookies (formato Netscape) para descargar videos de YouTube que requieren sesión o ante bloqueos (403) persistentes |
| `EDGETAPE_YT_CLIENT_ID` | Client ID de Google Cloud para OAuth de YouTube (upload) |
| `EDGETAPE_YT_CLIENT_SECRET` | Client secret de Google Cloud para OAuth de YouTube |
| `EDGETAPE_ASYNC_BACKEND` | Backend async: `local` (en proceso uvicorn), `celery` (requiere Redis + worker) |
| `EDGETAPE_METADATA_DELAY` | Pausa deliberada entre scoring y metadata (segundos; default `5`; `0` acelera tests) |
| `EDGETAPE_QUEUE_TASK_DELAY` | Pausa entre tareas de la cola de publicación (segundos; default `10`) |
| `EDGETAPE_OLLAMA_PROBE` | Probe de Ollama al construir el generador de metadata (`0` lo desactiva; default `1`) |
| `EDGETAPE_PEXELS_API_KEY` / `EDGETAPE_PIXABAY_API_KEY` | Claves gratuitas de b-roll. Con una basta; sin ellas el motor cae a Wikimedia/fondos de marca |
| `EDGETAPE_STOCK_MATERIALS` | `0` desactiva todo el material de stock |
| `EDGETAPE_MUSIC_DIR` | Carpeta de pistas de música (default `backend/assets/music`) |
| `EDGETAPE_MUSIC_VOLUME` | Mezcla de la música bajo la voz (default `0.22`) |
| `EDGETAPE_VIDEOGEN_BASE_URL` / `_API_KEY` / `_MODEL` / `_MODE` | Proveedor opcional de material generado por IA. `MODE=image` (OpenAI-compatible) o `webhook`. Sin esto no se usa |
| `EDGETAPE_VIDEOGEN_MAX_SCENES` | Tope de escenas por job que pueden usar material IA (default `1`) |
| `EDGETAPE_VIDEOGEN` | `0` desactiva el proveedor aunque esté configurado |
| `EDGETAPE_PUBLIC_BASE_URL` | **Dominio público** del deploy. Necesario para Instagram: Meta debe poder descargar el clip desde la URL firmada |
| `EDGETAPE_TIKTOK_CLIENT_KEY` / `_CLIENT_SECRET` / `_REDIRECT_URI` | Credenciales de la app de TikTok (también se pueden guardar por cuenta en CUENTAS) |
| `EDGETAPE_TIKTOK_PRIVACY` | `SELF_ONLY` (default) o `PUBLIC_TO_EVERYONE`; TikTok solo acepta público con la app auditada |
| `EDGETAPE_META_CLIENT_ID` / `_CLIENT_SECRET` / `_REDIRECT_URI` | Credenciales de la app de Meta (Facebook Login) |

**Prioridad de transcripción**: Groq (si hay `EDGETAPE_GROQ_API_KEY`) → `faster-whisper` local → mock.

**Prioridad de metadata viral**: Groq (si hay API key) → API remota → Ollama local → heurístico.

**Límites de YouTube API**: cuenta nueva/verificada = 6 videos/día. Se resetea a medianoche (hora del Pacífico).

**TikTok y Meta**: sin app aprobada, TikTok solo publica en privado (`SELF_ONLY`). Instagram necesita
`EDGETAPE_PUBLIC_BASE_URL` con un dominio real y accesible desde internet; sin él, el Reel se registra
como publicación manual. Las credenciales pueden ir por entorno **o** por cuenta en CUENTAS (ganan las
de la cuenta).

**Almacenamiento**: cada job guarda su fuente, exports y miniaturas en `backend/storage/{job_id}/`.
`DELETE /api/jobs/{id}/media` libera el espacio de uno, y `python -m app.cleanup` barre `previous/` y
los `ai_tmp` huérfanos de todo el storage (`--days`, `--keep`, `--job`).
`EDGETAPE_STORAGE` debe ser una ruta **absoluta** del sistema donde corre: una ruta de otro SO
(p. ej. `C:/...` dentro del contenedor) hace fallar ffmpeg en cada job.

El selector LLM se activa si existe cualquiera de las variables `EDGETAPE_LLM_*`. Si el modelo falla o no hay config, el pipeline cae al heurístico automáticamente. El job expone qué selector se usó en `job.scorer`.

> **Nota YouTube (HTTP 403)**: si la descarga falla con `HTTP Error 403: Forbidden`, actualiza yt-dlp
> (`pip install -U yt-dlp`). La descarga ya reintenta con distintos "player clients" de YouTube y usa
> User-Agent de navegador. Para casos persistentes, exporta tus cookies de YouTube a un archivo
> Netscape (p. ej. con una extensión de cookies) y apúntalo con `EDGETAPE_YT_COOKIES`.

## Próximos pasos / extensiones naturales

- Importar vistas/ganancias automáticamente desde YouTube Analytics / TikTok / Meta APIs.
- Historial de versiones de un video generado (hoy solo se guarda la anterior en `previous/`).
- Características acústicas (energía/risas) vía ffmpeg como señal adicional de momento fuerte.
- Ajuste manual de in/out en el frontend antes de exportar.
- Recorte sin recodificación (`-c copy`) cuando el usuario priorice velocidad.
- Soporte para múltiples cuentas por plataforma y usuario.
