# ── Multi-stage: build del frontend (web/dist) + backend Python con ffmpeg ──

# Stage 1: compila el frontend con pnpm
FROM node:20-alpine AS web
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# Stage 2: runtime Python del backend
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg gosu && \
    rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios: la app no corre como root.
RUN groupadd -g 10001 edgetape && \
    useradd -u 10001 -g edgetape -m -s /bin/sh edgetape

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=web /web/dist ./web/dist
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R edgetape:edgetape /app

WORKDIR /app/backend
# EDGETAPE_ROLE=api | worker | all (default: all → API + worker en un solo contenedor)
ENV EDGETAPE_ROLE=all
EXPOSE 8000
CMD ["/entrypoint.sh"]