#!/usr/bin/env sh
set -eu

# Run migrations before serving traffic so the app and database schema stay in sync.
alembic upgrade head

# Start the FastAPI application. Uvicorn is used directly to keep the container simple.
exec uvicorn job_logger.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" --proxy-headers

