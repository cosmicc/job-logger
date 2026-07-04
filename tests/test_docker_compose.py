"""Regression tests for Docker Compose deployment behavior."""

from __future__ import annotations

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
SWARM_FILE = Path(__file__).resolve().parents[1] / "docker-swarm.yml"
ENV_EXAMPLE_FILE = Path(__file__).resolve().parents[1] / ".env.example"
README_FILE = Path(__file__).resolve().parents[1] / "README.md"
EXTERNAL_NGINX_FILE = Path(__file__).resolve().parents[1] / "docs/external-nginx-job-logger.conf"


def test_compose_does_not_gate_stack_creation_on_health_conditions() -> None:
    """Portainer should create containers even while services become healthy."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "condition: service_healthy" not in compose_text
    assert "The app entrypoint waits briefly for real database connectivity" in compose_text
    assert "start_period: 60s" in compose_text
    assert "retries: 12" in compose_text


def test_compose_exposes_log_level_setting() -> None:
    """Docker Compose should pass the stdout app log level into the container."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "LOG_LEVEL: ${LOG_LEVEL:-INFO}" in compose_text
    assert "LOG_DIR:" not in compose_text
    assert "HOST_LOG_DIR" not in compose_text
    assert "LOGIN_FAILURE_LOG_PATH" not in compose_text
    assert "LOGIN_SUCCESS_LOG_PATH" not in compose_text


def test_compose_exposes_dev_build_setting() -> None:
    """Docker Compose should pass the dev-build marker into the container."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "DEV_BUILD: ${DEV_BUILD:-false}" in compose_text


def test_compose_exposes_cloudflare_block_settings() -> None:
    """Docker Compose should pass app-managed Cloudflare block settings into the app."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "CLOUDFLARE_IP_BLOCKING_ENABLED: ${CLOUDFLARE_IP_BLOCKING_ENABLED:-false}" in compose_text
    assert "CLOUDFLARE_API_TOKEN: ${CLOUDFLARE_API_TOKEN:-}" in compose_text
    assert "CLOUDFLARE_ZONE_ID: ${CLOUDFLARE_ZONE_ID:-}" in compose_text
    assert "CLOUDFLARE_IP_BLOCK_ALLOWLIST: ${CLOUDFLARE_IP_BLOCK_ALLOWLIST:-}" in compose_text
    assert "CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS: ${CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS:-5}" in compose_text
    assert "LOGIN_LOCAL_LOCKOUT_MINUTES: ${LOGIN_LOCAL_LOCKOUT_MINUTES:-15}" in compose_text


def test_compose_requires_app_and_database_secrets() -> None:
    """A bare Compose run should fail closed instead of using development secrets."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://" in compose_text
    assert "APP_ENV: ${APP_ENV:-production}" in compose_text
    assert "APP_SECRET_KEY: ${APP_SECRET_KEY:?Set APP_SECRET_KEY in .env}" in compose_text
    assert "APP_PASSWORD: ${APP_PASSWORD:?Set APP_PASSWORD in .env}" in compose_text
    assert "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}" in compose_text
    assert "development-only-change-me" not in compose_text
    assert "APP_PASSWORD: ${APP_PASSWORD:-admin}" not in compose_text
    assert "job_logger_password" not in compose_text
    assert "APP_SESSION_COOKIE_SECURE: ${APP_SESSION_COOKIE_SECURE:-true}" in compose_text
    assert "CLOUDFLARE_ACCESS_REQUIRED: ${CLOUDFLARE_ACCESS_REQUIRED:-true}" in compose_text


def test_compose_database_container_uses_local_profile() -> None:
    """The bundled PostgreSQL service should be optional for remote DB deployments."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "profiles:\n      - local-db" in compose_text
    assert "depends_on:\n      - db" not in compose_text


def test_compose_bundled_edge_services_use_shared_profile() -> None:
    """Bundled nginx and cloudflared should be toggled together."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    nginx_index = compose_text.index("  nginx:")
    db_index = compose_text.index("\n  db:", nginx_index)
    nginx_block = compose_text[nginx_index:db_index]
    cloudflared_index = compose_text.index("  cloudflared:")
    volumes_index = compose_text.index("\nvolumes:", cloudflared_index)
    cloudflared_block = compose_text[cloudflared_index:volumes_index]

    assert "profiles:\n      - bundled-edge" in nginx_block
    assert "profiles:\n      - bundled-edge" in cloudflared_block
    assert "depends_on:\n      - nginx" in cloudflared_block
    assert "NGINX_ACCESS_LOG: ${NGINX_ACCESS_LOG:-/dev/stdout}" in nginx_block
    assert "NGINX_ERROR_LOG: ${NGINX_ERROR_LOG:-/dev/stderr warn}" in nginx_block


def test_compose_exposes_database_pool_settings() -> None:
    """Remote PostgreSQL deployments should have bounded reusable connections."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "DATABASE_CONNECT_TIMEOUT_SECONDS: ${DATABASE_CONNECT_TIMEOUT_SECONDS:-5}" in compose_text
    assert "DATABASE_POOL_SIZE: ${DATABASE_POOL_SIZE:-5}" in compose_text
    assert "DATABASE_MAX_OVERFLOW: ${DATABASE_MAX_OVERFLOW:-10}" in compose_text
    assert "DATABASE_POOL_TIMEOUT_SECONDS: ${DATABASE_POOL_TIMEOUT_SECONDS:-30}" in compose_text
    assert "DATABASE_POOL_RECYCLE_SECONDS: ${DATABASE_POOL_RECYCLE_SECONDS:-1800}" in compose_text
    assert "DATABASE_UNAVAILABLE_CHECK_INTERVAL_SECONDS: ${DATABASE_UNAVAILABLE_CHECK_INTERVAL_SECONDS:-5}" in compose_text
    assert "APP_HEALTH_DB_LATENCY_WARNING_MS: ${APP_HEALTH_DB_LATENCY_WARNING_MS:-250}" in compose_text
    assert "APP_HEALTH_DB_POOL_WARNING_PERCENT: ${APP_HEALTH_DB_POOL_WARNING_PERCENT:-80}" in compose_text


def test_compose_and_swarm_expose_pushover_health_settings() -> None:
    """Pushover health notification settings should pass through container configs."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    swarm_text = SWARM_FILE.read_text(encoding="utf-8")
    env_example_text = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")

    for deployment_text in (compose_text, swarm_text):
        assert "APP_HEALTH_MONITOR_INTERVAL_SECONDS: ${APP_HEALTH_MONITOR_INTERVAL_SECONDS:-300}" in deployment_text
        assert "APP_HEALTH_DB_LATENCY_CRITICAL_MS: ${APP_HEALTH_DB_LATENCY_CRITICAL_MS:-1000}" in deployment_text
        assert "APP_HEALTH_DB_POOL_CRITICAL_PERCENT: ${APP_HEALTH_DB_POOL_CRITICAL_PERCENT:-95}" in deployment_text
        assert "PUSHOVER_ENABLED: ${PUSHOVER_ENABLED:-false}" in deployment_text
        assert "PUSHOVER_USER_KEY: ${PUSHOVER_USER_KEY:-}" in deployment_text
        assert "PUSHOVER_APP_KEY: ${PUSHOVER_APP_KEY:-}" in deployment_text
        assert "PUSHOVER_API_URL: ${PUSHOVER_API_URL:-https://api.pushover.net/1/messages.json}" in deployment_text
        assert "PUSHOVER_TIMEOUT_SECONDS: ${PUSHOVER_TIMEOUT_SECONDS:-10}" in deployment_text

    assert "PUSHOVER_USER_KEY=" in env_example_text
    assert "PUSHOVER_APP_KEY=" in env_example_text
    assert "external monitor" in env_example_text


def test_compose_and_swarm_expose_help_assistant_settings() -> None:
    """OpenAI help assistant settings should pass through container configs."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    swarm_text = SWARM_FILE.read_text(encoding="utf-8")
    env_example_text = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")

    for deployment_text in (compose_text, swarm_text):
        assert "HELP_ASSISTANT_ENABLED: ${HELP_ASSISTANT_ENABLED:-false}" in deployment_text
        assert "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in deployment_text
        assert "HELP_ASSISTANT_MODEL: ${HELP_ASSISTANT_MODEL:-gpt-5.4-mini}" in deployment_text
        assert "HELP_ASSISTANT_API_BASE_URL: ${HELP_ASSISTANT_API_BASE_URL:-https://api.openai.com/v1}" in deployment_text
        assert "HELP_ASSISTANT_TIMEOUT_SECONDS: ${HELP_ASSISTANT_TIMEOUT_SECONDS:-20}" in deployment_text
        assert "HELP_ASSISTANT_MAX_QUESTION_CHARS: ${HELP_ASSISTANT_MAX_QUESTION_CHARS:-1200}" in deployment_text
        assert "HELP_ASSISTANT_MAX_CONTEXT_CHARS: ${HELP_ASSISTANT_MAX_CONTEXT_CHARS:-60000}" in deployment_text
        assert "HELP_ASSISTANT_INSTRUCTIONS: ${HELP_ASSISTANT_INSTRUCTIONS:-}" in deployment_text

    assert "HELP_ASSISTANT_ENABLED=false" in env_example_text
    assert "OPENAI_API_KEY=" in env_example_text
    assert "HELP_ASSISTANT_INSTRUCTIONS=" in env_example_text


def test_env_example_defaults_to_bundled_profiles_and_documents_switching() -> None:
    """The sample env should preserve bundled defaults and document deployment switching."""

    env_example_text = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")

    assert "COMPOSE_PROFILES=local-db,bundled-edge" in env_example_text
    assert "For a remote PostgreSQL server, remove `local-db`" in env_example_text
    assert "For an external nginx and" in env_example_text
    assert "remove `bundled-edge`" in env_example_text
    assert "JOB_LOGGER_BUNDLED_EDGE_REPLICAS=1" in env_example_text
    assert "JOB_LOGGER_SWARM_STORAGE_PATH=/mnt/swarm-storage/job-logger" in env_example_text
    assert "DATABASE_URL=" in env_example_text
    assert "DATABASE_POOL_RECYCLE_SECONDS=1800" in env_example_text
    assert "LOG_DIR=/data/logs" in env_example_text
    assert "CLOUDFLARED_LOG_FILE=/var/log/cloudflared/cloudflared.log" in env_example_text
    assert "HOST_LOG_DIR=" not in env_example_text
    assert "LOGIN_FAILURE_LOG_PATH=" not in env_example_text
    assert "LOGIN_SUCCESS_LOG_PATH=" not in env_example_text


def test_nginx_host_port_uses_localhost_and_http_port() -> None:
    """Nginx should bind only to localhost for the Cloudflare Tunnel origin."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert '"127.0.0.1:${HTTP_PORT:-11030}:80"' in compose_text
    assert "network_mode: \"host\"" in compose_text


def test_swarm_compose_uses_images_remote_database_optional_edge_and_shared_storage() -> None:
    """Docker Swarm should use images, remote DB, optional edge, and shared storage."""

    swarm_text = SWARM_FILE.read_text(encoding="utf-8")
    app_index = swarm_text.index("  app:")
    nginx_index = swarm_text.index("\n  nginx:", app_index)
    app_block = swarm_text[app_index:nginx_index]
    cloudflared_index = swarm_text.index("\n  cloudflared:", nginx_index)
    nginx_block = swarm_text[nginx_index:cloudflared_index]
    networks_index = swarm_text.index("\nnetworks:", cloudflared_index)
    cloudflared_block = swarm_text[cloudflared_index:networks_index]

    assert "build:" not in swarm_text
    assert "image: ${JOB_LOGGER_APP_IMAGE" in swarm_text
    assert "image: ${JOB_LOGGER_NGINX_IMAGE" in swarm_text
    assert "replicas: 1" in app_block
    assert "JOB_LOGGER_BUNDLED_EDGE_REPLICAS" not in app_block
    assert "replicas: ${JOB_LOGGER_BUNDLED_EDGE_REPLICAS:-1}" in nginx_block
    assert "replicas: ${JOB_LOGGER_BUNDLED_EDGE_REPLICAS:-1}" in cloudflared_block
    assert "${CLOUDFLARE_TUNNEL_TOKEN:-not-set}" in cloudflared_block
    assert "DATABASE_URL: ${DATABASE_URL:?Set DATABASE_URL to the remote PostgreSQL URL}" in swarm_text
    assert "LOG_LEVEL: ${LOG_LEVEL:-INFO}" in swarm_text
    assert "LOG_DIR: ${LOG_DIR:-/data/logs}" in app_block
    assert "LOGIN_FAILURE_LOG_PATH" not in swarm_text
    assert "LOGIN_SUCCESS_LOG_PATH" not in swarm_text
    assert "JOB_LOGGER_SWARM_STORAGE_PATH:-/mnt/swarm-storage/job-logger" in swarm_text
    assert "target: /data/logs" in app_block
    assert "target: /data/backups" in app_block
    assert "target: /models/faster-whisper" in app_block
    assert "target: /var/log/nginx" in nginx_block
    assert "target: /var/log/cloudflared" in cloudflared_block
    assert "NGINX_ACCESS_LOG: ${NGINX_ACCESS_LOG:-/var/log/nginx/access.log}" in nginx_block
    assert "NGINX_ERROR_LOG: ${NGINX_ERROR_LOG:-/var/log/nginx/error.log warn}" in nginx_block
    assert "--logfile" in cloudflared_block
    assert "${CLOUDFLARED_LOG_FILE:-/var/log/cloudflared/cloudflared.log}" in cloudflared_block
    assert "faster_whisper_models:" not in swarm_text
    assert "automatic_backups:" not in swarm_text
    assert "driver: overlay" in swarm_text
    assert "deploy:" in swarm_text
    assert "network_mode" not in swarm_text
    assert "postgres:16-alpine" not in swarm_text


def test_readme_documents_external_edge_profile_and_swarm_nginx_sample() -> None:
    """Operators should have clear docs for omitting the bundled web edge."""

    readme_text = README_FILE.read_text(encoding="utf-8")
    external_nginx_text = EXTERNAL_NGINX_FILE.read_text(encoding="utf-8")

    assert "COMPOSE_PROFILES=local-db,bundled-edge" in readme_text
    assert "COMPOSE_PROFILES=local-db" in readme_text
    assert "JOB_LOGGER_BUNDLED_EDGE_REPLICAS=0" in readme_text
    assert "JOB_LOGGER_SWARM_STORAGE_PATH=/mnt/swarm-storage/job-logger" in readme_text
    assert "logs/cloudflared/" in readme_text
    assert "models/faster-whisper/" in readme_text
    assert "docs/external-nginx-job-logger.conf" in readme_text
    assert "proxy to `http://job_logger_app:8000`" in readme_text
    assert "proxy_pass http://job_logger_app:8000" in external_nginx_text
