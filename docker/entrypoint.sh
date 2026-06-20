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
import sys

import psycopg
from sqlalchemy.engine import make_url


def _connect(raw_url: str) -> None:
    database_url = make_url(raw_url)
    if not database_url.host:
        raise RuntimeError("DATABASE_URL must include a host.")

    with psycopg.connect(
        dbname=database_url.database,
        user=database_url.username,
        password=database_url.password,
        host=database_url.host,
        port=database_url.port or 5432,
        connect_timeout=2,
    ):
        return


try:
    _connect(sys.argv[1])
except psycopg.OperationalError as exc:
    # Keep startup diagnostics sanitized. Authentication failures are permanent
    # until the persisted database user password is changed, so do not hide them
    # behind transient retry messages.
    error_text = str(exc).splitlines()[0].lower()
    if "password authentication failed" in error_text:
        print("db_error=password_authentication_failed")
        raise SystemExit(2)
    if "does not exist" in error_text:
        print("db_error=database_or_user_missing")
        raise SystemExit(2)
    print("db_error=temporarily_unreachable")
    raise SystemExit(1)
except Exception:
    # Keep output low risk: do not echo DATABASE_URL because it contains secrets.
    print("db_error=configuration_or_driver_failure")
    raise SystemExit(1)

print("db_ready")
PY
    then
      echo "Database connection established."
      return 0
    else
      connection_result="$?"
    fi

    if [ "$connection_result" -eq 2 ]; then
      echo "Database authentication/configuration failed. Check that the persisted PostgreSQL user password matches POSTGRES_PASSWORD in the deployment environment."
      return 1
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

prepare_log_paths() {
  # LOG_DIR is the app-side path; Docker Compose bind-mounts the host log
  # directory there so operators can read app.log and failed-login JSONL files.
  log_dir="${LOG_DIR:-/data/logs}"
  login_failure_log_path="${LOGIN_FAILURE_LOG_PATH:-${log_dir%/}/job-logger-login-failures.log}"

  mkdir -p "$log_dir" "$(dirname "$login_failure_log_path")"
  if [ -d "$login_failure_log_path" ]; then
    echo "LOGIN_FAILURE_LOG_PATH points to a directory, expected a writable log file: ${login_failure_log_path}" >&2
    exit 1
  fi
  touch "$login_failure_log_path"
  chown -R appuser:appuser "$log_dir"
  chown appuser:appuser "$login_failure_log_path"
  chmod 0750 "$log_dir"
  chmod 0640 "$login_failure_log_path"
}

run_as_appuser() {
  if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
  fi
  exec "$@"
}

if [ "$(id -u)" = "0" ]; then
  prepare_log_paths
fi

# Run migrations after the database is reachable so startup does not fail at image
# boot when DNS or startup ordering is temporarily out of sync.
wait_for_database

# Run migrations before serving traffic so the app and database schema stay in sync.
if [ "$(id -u)" = "0" ]; then
  gosu appuser alembic upgrade head
else
  alembic upgrade head
fi

# Start the FastAPI application. Uvicorn is used directly to keep the container simple.
run_as_appuser uvicorn job_logger.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" --proxy-headers
