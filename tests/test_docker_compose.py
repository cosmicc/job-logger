"""Regression tests for Docker Compose deployment behavior."""

from __future__ import annotations

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_compose_does_not_gate_stack_creation_on_health_conditions() -> None:
    """Portainer should create containers even while services become healthy."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "condition: service_healthy" not in compose_text
    assert "The app entrypoint waits for real database connectivity" in compose_text
    assert "start_period: 60s" in compose_text
    assert "retries: 12" in compose_text


def test_compose_exposes_log_level_setting() -> None:
    """Docker Compose should pass the app log level into the container."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "LOG_LEVEL: ${LOG_LEVEL:-INFO}" in compose_text


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

    assert "APP_ENV: ${APP_ENV:-production}" in compose_text
    assert "APP_SECRET_KEY: ${APP_SECRET_KEY:?Set APP_SECRET_KEY in .env}" in compose_text
    assert "APP_PASSWORD: ${APP_PASSWORD:?Set APP_PASSWORD in .env}" in compose_text
    assert "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}" in compose_text
    assert "development-only-change-me" not in compose_text
    assert "APP_PASSWORD: ${APP_PASSWORD:-admin}" not in compose_text
    assert "job_logger_password" not in compose_text
    assert "APP_SESSION_COOKIE_SECURE: ${APP_SESSION_COOKIE_SECURE:-true}" in compose_text
    assert "CLOUDFLARE_ACCESS_REQUIRED: ${CLOUDFLARE_ACCESS_REQUIRED:-true}" in compose_text


def test_nginx_host_port_uses_localhost_and_http_port() -> None:
    """Nginx should bind only to localhost for the Cloudflare Tunnel origin."""

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")

    assert '"127.0.0.1:${HTTP_PORT:-11030}:80"' in compose_text
    assert "network_mode: \"host\"" in compose_text
