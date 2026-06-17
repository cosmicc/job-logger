#!/usr/bin/env sh
set -eu

# Keep startup resilient when the database service is temporarily unavailable at
# container boot time (for example under Docker Swarm/stack where dependency
# health checks are best-effort and the `db` service name might appear late).
wait_for_database() {
  # Match entrypoint and migration behavior with the same default when no env var is set.
  database_url="${DATABASE_URL:-postgresql+psycopg://job_logger:job_logger_password@db:5432/job_logger}"
  timeout_seconds="${DATABASE_CONNECT_TIMEOUT_SECONDS:-60}"
  sleep_seconds="${DATABASE_CONNECT_RETRY_DELAY_SECONDS:-2}"
  attempt=1
  max_attempts=$((timeout_seconds / sleep_seconds))

  if [ "$max_attempts" -lt 1 ]; then
    max_attempts=1
  fi

  echo "Waiting for database connectivity (${attempt}/${max_attempts}) using DATABASE_URL host..."

  while [ "$attempt" -le "$max_attempts" ]; do
    if python - "$database_url" <<'PY'
from urllib.parse import urlparse
import sys

import psycopg


def _connect(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if not parsed.hostname:
        raise RuntimeError("DATABASE_URL must include a host.")

    with psycopg.connect(
        dbname=(parsed.path or "/").lstrip("/") or None,
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        connect_timeout=2,
    ):
        return


try:
    _connect(sys.argv[1])
except Exception as exc:
    # Keep output low risk: no credentials are echoed in exception text here.
    raise SystemExit(1)

print("db_ready")
PY
    then
      echo "Database connection established."
      return 0
    fi

    if [ "$attempt" -ge "$max_attempts" ]; then
      break
    fi

    sleep "$sleep_seconds"
    attempt=$((attempt + 1))
    echo "Database not ready yet, retrying (${attempt}/${max_attempts})..."
  done

  echo "Database did not become reachable within ${timeout_seconds}s."
  return 1
}

# Run migrations after the database is reachable so startup does not fail at image
# boot when DNS or startup ordering is temporarily out of sync.
wait_for_database

# Run migrations before serving traffic so the app and database schema stay in sync.
alembic upgrade head

# Start the FastAPI application. Uvicorn is used directly to keep the container simple.
exec uvicorn job_logger.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" --proxy-headers
