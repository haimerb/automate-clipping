# Diagramas del flujo

## `pipeline.mmd`

Diagrama Mermaid del pipeline de edgetape:

INGRESAR → Cola Celery/Redis → `process_job` (descarga → transcripción → scoring LLM/heurístico) → metadata viral → clips → límites de duración por formato → export vertical → miniaturas virales → storage JSON → API + JWT → cola de publicación persistente → upload YouTube v3 (o respaldo Studio) → posts.json → dashboard.

Para renderizarlo:

- GitHub renderiza `.mmd` automáticamente.
- Local: `npx -y @mermaid-js/mermaid-cli` (instala mmdc) o pega el contenido en https://mermaid.live.