# Documentación de edgetape

## `deploy-remoto.md`

Runbook de despliegue y credenciales: dominio público y `EDGETAPE_PUBLIC_BASE_URL`, registro de
las apps de TikTok, Meta y Google Cloud, y rotación de claves. Es el primero que hay que leer
para publicar de verdad.

## `deploy-free.md`

Alojamiento sin tarjeta (HF Spaces + Neon + Upstash) y el límite diario del canal de YouTube.

## `pipeline.mmd`

Diagrama Mermaid del pipeline de edgetape:

**Ingesta** (archivo, URL con yt-dlp o generación con IA) → Cola Celery/Redis → `process_job` (descarga → transcripción → scoring LLM/heurístico) → metadata viral → clips → límites de duración por formato → export vertical → miniaturas virales → storage JSON → API + JWT → cola de publicación persistente → upload (YouTube v3, TikTok Content Posting API, Facebook Graph o Instagram Reels con URL firmada; con respaldo a Studio cuando no hay OAuth) → posts.json → dashboard.

El subgrafo **MOTOR DE VIDEO GENERADO** (`ai_generate`) es la cascada del job `generate`, donde
ninguna degradación es silenciosa. El guion parte de un *fact sheet* del tema (entidades, hechos y
sujeto visual), se escribe por bloques y se verifica con `topic_coverage`; si baja del umbral se
regenera una vez. La voz se sintetiza por oración con duraciones reales (`narration.py`:
edge-tts → gTTS → sin voz) para que escenas y subtítulos no se desincronicen. El material prioriza
imágenes reales del sujeto (Wikimedia Commons) → stock Pexels/Pixabay → imagen IA sin watermark
(Cloudflare FLUX) → `videogen` → Wikimedia por oración → hero shots de video IA (HF ZeroGPU,
image-to-video) → fondos de marca. Cada proveedor gratis lleva cuota diaria UTC (`quota.py`) y
cada salto hacia abajo se acumula en `job.warning`. El montaje usa cortes limpios, grade
unificado, subtítulos por cláusula y música con *ducking*; el reporte por escena queda en
`visual_report.json`.

Para renderizarlo:

- GitHub renderiza `.mmd` automáticamente.
- Local: `npx -y @mermaid-js/mermaid-cli` (instala mmdc) o pega el contenido en https://mermaid.live.

## Limpieza de disco

`python -m app.cleanup` recorta `storage/{job}/previous/` (conservando `--keep` versiones más las
que no superen `--days`) y borra los `ai_tmp` de jobs terminados o inexistentes.
`DELETE /api/jobs/{id}/media` hace lo mismo para un solo job conservando su JSON.
