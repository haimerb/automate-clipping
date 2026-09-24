# Copilot Instructions: Edgetape

Edgetape is a video/audio clipping automation platform that converts long recordings into AI-detected viral clips.

## Build and Test Commands

### Backend (FastAPI)
- **Run API**: `uvicorn app.main:app --reload --app-dir backend`
- **Run Worker (Celery)**: `cd backend && celery -A app.tasks worker --pool=solo --loglevel=info` (or use `.\start-worker.bat` on Windows)
- **Run All Tests**: `cd backend && python -m pytest`
- **Run Single Test File**: `cd backend && python -m pytest tests/test_<module>.py`
- **Run Specific Test**: `cd backend && python -m pytest tests/test_<module>.py::test_<function_name>`

### Frontend (React + Vite + TS)
- **Dev Mode**: `cd web && npm run dev`
- **Build**: `cd web && npm run build` (includes `tsc --noEmit` for type checking)

### Infrastructure
- **Start Dependencies**: `docker compose up -d` (Postgres 16 and Redis 7)

## High-Level Architecture

- **Backend**: FastAPI application utilizing a hybrid storage model:
    - **PostgreSQL**: Stores users, authentication sessions, and linked platform accounts.
    - **JSON Files**: Jobs, clips, and platform posts are persisted as JSON in `backend/storage/{job_id}/` to allow for easier portability and isolation.
- **Job Pipeline**:
    1. **Download**: via `yt-dlp` (for YouTube) or file upload.
    2. **Transcription**: via Groq Whisper $\rightarrow$ faster-whisper $\rightarrow$ Mock (fallback).
    3. **Scoring**: Hybrid approach using heuristic thresholds (adaptive $\mu + 0.4\sigma$) and LLM selection.
    4. **Export**: `ffmpeg` handles clipping and vertical formatting (`vertical_blur` or `vertical_crop`).
    5. **Publication**: Parallel upload to YouTube (API v3), TikTok, and Facebook.
- **Frontend**: React app using Material UI v9 with a specific design token system defined in `src/theme.ts`.

## Key Conventions

### Backend
- **Async Execution**: Background tasks use Celery + Redis. Ensure the worker is running; otherwise, jobs remain in `queued` status.
- **Configuration**: All secrets and URLs are environment-driven (via `.env`). No hardcoded credentials.
- **Lazy Imports**: Large AI models (faster-whisper) and network-heavy libraries (yt-dlp) are imported inside functions to optimize startup time.
- **Auth**: All job/post endpoints require a Bearer token and verify ownership (returns 404, not 403, on ownership failure).

### Frontend
- **MUI v9**: Follow MUI v9 breaking changes:
    - Use `sx` for `Stack` alignment/justification.
    - Use `slotProps={{ htmlInput: {...} }}` for `TextField` input properties.
    - Use `size={{ xs, sm, md }}` for `Grid` instead of `item` or `xs/md` props.
- **Design**: Strictly adhere to design tokens in `src/theme.ts` (EDGE: `#1E3A8A`, MARK: `#FFC647`). Use Fragment Mono for timestamps.

### General
- **Tests**: Backend tests use a temporary SQLite database via `conftest.py`, so they can run without Postgres.
