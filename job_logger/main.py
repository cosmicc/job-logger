"""FastAPI application factory and middleware configuration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url
from starlette.middleware.sessions import SessionMiddleware

from job_logger.config import Settings, settings
from job_logger.logging_config import configure_logging
from job_logger.routes import auth, changelog, configuration, debug, health, mobile, passkeys, pwa, review, users
from job_logger.services.backups import automatic_backup_scheduler
from job_logger.session_timeout import SessionTimeoutMiddleware

# These are unsafe sentinel values used only so startup can reject them.
DEVELOPMENT_APP_PASSWORD = "admin"  # nosec B105
DEVELOPMENT_DATABASE_PASSWORD = "job_logger_password"  # nosec B105
DEVELOPMENT_SECRET_KEY = "development-only-change-me"  # nosec B105
HSTS_HEADER_VALUE = "max-age=15552000"
PLACEHOLDER_SECRET_PREFIX = "replace-with-"  # nosec B105


def _database_password(database_url: str) -> str | None:
    """Return the database password from DATABASE_URL when it can be parsed."""

    try:
        return make_url(database_url).password
    except Exception:
        return None


def _is_placeholder_secret(value: str | None) -> bool:
    """Return whether a configured secret still looks like a documented placeholder."""

    return bool(value and value.strip().lower().startswith(PLACEHOLDER_SECRET_PREFIX))


def _database_uses_unsafe_password(database_url: str) -> bool:
    """Return whether DATABASE_URL still contains a default or placeholder password."""

    parsed_password = _database_password(database_url)
    if parsed_password is not None:
        return parsed_password == DEVELOPMENT_DATABASE_PASSWORD or _is_placeholder_secret(parsed_password)

    return f":{DEVELOPMENT_DATABASE_PASSWORD}@" in database_url or f":{PLACEHOLDER_SECRET_PREFIX}" in database_url.lower()


def validate_runtime_settings(application_settings: Settings) -> None:
    """Fail fast when production settings would expose the app unsafely."""

    uses_development_app_password = application_settings.app_password == DEVELOPMENT_APP_PASSWORD
    uses_development_secret = application_settings.app_secret_key == DEVELOPMENT_SECRET_KEY
    if not application_settings.is_production:
        return

    if uses_development_secret or _is_placeholder_secret(application_settings.app_secret_key):
        raise RuntimeError("APP_SECRET_KEY must be replaced in production.")

    if len(application_settings.app_secret_key) < 32:
        raise RuntimeError("APP_SECRET_KEY must be at least 32 characters in production.")

    if not application_settings.app_password:
        raise RuntimeError("APP_PASSWORD must be configured in production.")

    if uses_development_app_password or _is_placeholder_secret(application_settings.app_password):
        raise RuntimeError("APP_PASSWORD must not use the development default or documented placeholder in production.")

    if _database_uses_unsafe_password(application_settings.database_url):
        raise RuntimeError("POSTGRES_PASSWORD/DATABASE_URL must not use the development default or documented placeholder in production.")

    if not application_settings.session_cookie_secure:
        raise RuntimeError("APP_SESSION_COOKIE_SECURE=true is required in production.")

    if application_settings.autotask_provider != "autotask":
        raise RuntimeError("AUTOTASK_PROVIDER=autotask is required in production.")


def create_app(application_settings: Settings = settings) -> FastAPI:
    """Create and configure the FastAPI application."""

    configure_logging(application_settings)
    validate_runtime_settings(application_settings)
    fastapi_app = FastAPI(title="Job Logger", docs_url=None, redoc_url=None, openapi_url=None)

    fastapi_app.add_middleware(SessionTimeoutMiddleware, application_settings=application_settings)
    fastapi_app.add_middleware(
        SessionMiddleware,
        secret_key=application_settings.app_secret_key,
        session_cookie="job_logger_session",
        https_only=application_settings.session_cookie_secure,
        same_site="lax",
        max_age=application_settings.session_timeout_seconds,
    )

    fastapi_app.mount("/static", StaticFiles(directory="job_logger/static"), name="static")

    if application_settings.automatic_backups_enabled:

        @fastapi_app.on_event("startup")
        async def start_automatic_backups() -> None:
            """Start the hourly full-data backup task for this app process."""

            fastapi_app.state.automatic_backup_task = asyncio.create_task(
                automatic_backup_scheduler(application_settings)
            )

        @fastapi_app.on_event("shutdown")
        async def stop_automatic_backups() -> None:
            """Stop the automatic backup task cleanly during application shutdown."""

            backup_task = getattr(fastapi_app.state, "automatic_backup_task", None)
            if backup_task is None:
                return

            backup_task.cancel()
            with suppress(asyncio.CancelledError):
                await backup_task

    @fastapi_app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Add defensive browser headers to every response."""

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        if application_settings.is_production:
            response.headers["Strict-Transport-Security"] = HSTS_HEADER_VALUE
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "worker-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "media-src 'self' blob:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

    @fastapi_app.middleware("http")
    async def require_cloudflare_access(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Optionally reject requests that did not pass through Cloudflare Access."""

        if application_settings.cloudflare_access_required:
            access_email = request.headers.get("cf-access-authenticated-user-email")
            if request.url.path != "/health/live" and not access_email:
                return Response("Cloudflare Access identity is required.", status_code=403)

        return await call_next(request)

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(pwa.router)
    fastapi_app.include_router(auth.router)
    fastapi_app.include_router(passkeys.router)
    fastapi_app.include_router(mobile.router)
    fastapi_app.include_router(configuration.router)
    fastapi_app.include_router(users.router)
    fastapi_app.include_router(changelog.router)
    fastapi_app.include_router(debug.router)
    fastapi_app.include_router(review.router)
    return fastapi_app


app = create_app()
