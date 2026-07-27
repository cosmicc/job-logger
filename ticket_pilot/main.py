"""FastAPI application factory and middleware configuration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from ticket_pilot.config import Settings, settings
from ticket_pilot.logging_config import configure_logging
from ticket_pilot.routes import auth, changelog, configuration, debug, health, help, mobile, passkeys, password_reset, pwa, review, users
from ticket_pilot.security import current_username
from ticket_pilot.services.app_health_monitor import app_health_notification_scheduler
from ticket_pilot.services.backups import automatic_backup_scheduler
from ticket_pilot.services.database_availability import (
    DatabaseAvailabilityMonitor,
    startup_migrations_are_pending,
)
from ticket_pilot.session_timeout import SessionTimeoutMiddleware
from ticket_pilot.ui import static_asset_version, template_context, templates

# These are unsafe sentinel values used only so startup can reject them.
DEVELOPMENT_APP_PASSWORD = "admin"  # nosec B105
DEVELOPMENT_DATABASE_PASSWORD = "ticket_pilot_password"  # nosec B105
DEVELOPMENT_SECRET_KEY = "development-only-change-me"  # nosec B105
HSTS_HEADER_VALUE = "max-age=15552000"
PLACEHOLDER_SECRET_PREFIX = "replace-with-"  # nosec B105
SERVICE_UNAVAILABLE_RETRY_SECONDS = 10
DATABASE_INDEPENDENT_PATHS = {
    "/health/live",
    "/manifest.webmanifest",
    "/service-worker.js",
}
DATABASE_INDEPENDENT_PREFIXES = (
    "/static/",
)
HTML_ERROR_TITLES = {
    400: "Bad request",
    401: "Sign-in required",
    403: "Access denied",
    404: "Page not found",
    405: "Action not allowed",
    408: "Request timeout",
    413: "Upload too large",
    429: "Too many requests",
}
HTML_ERROR_MESSAGES = {
    400: "That request could not be used by TicketPilot.",
    401: "Sign in again to continue using TicketPilot.",
    403: "Your current session cannot open that TicketPilot page.",
    404: "That TicketPilot page does not exist or is not available from this web address.",
    405: "That action is not available for this TicketPilot page.",
    408: "The request took too long to complete.",
    413: "That upload is larger than this TicketPilot page accepts.",
    429: "Too many requests reached TicketPilot in a short time.",
}


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


def _validate_password_reset_settings(application_settings: Settings) -> None:
    """Fail fast when password reset is enabled without safe dependencies."""

    if not application_settings.password_reset_enabled:
        return

    if not application_settings.app_public_base_url:
        raise RuntimeError("APP_PUBLIC_BASE_URL is required when PASSWORD_RESET_ENABLED=true.")

    parsed_public_url = urlparse(application_settings.app_public_base_url)
    if not parsed_public_url.scheme or not parsed_public_url.netloc:
        raise RuntimeError("APP_PUBLIC_BASE_URL must be an absolute URL when PASSWORD_RESET_ENABLED=true.")

    if application_settings.is_production and parsed_public_url.scheme != "https":
        raise RuntimeError("APP_PUBLIC_BASE_URL must use HTTPS in production when PASSWORD_RESET_ENABLED=true.")

    if not application_settings.password_reset_mail_configured:
        raise RuntimeError(
            "MAIL_ENABLED, MAIL_FROM_EMAIL, and either SMTP settings or MAIL_SMTP2GO_API_KEY "
            "are required when PASSWORD_RESET_ENABLED=true."
        )

    if (
        application_settings.mail_mode == "smtp"
        and application_settings.mail_smtp_ssl
        and application_settings.mail_smtp_starttls
    ):
        raise RuntimeError("MAIL_SMTP_SSL and MAIL_SMTP_STARTTLS cannot both be true.")

    if application_settings.turnstile_enabled and (
        not application_settings.turnstile_site_key or not application_settings.turnstile_secret_key
    ):
        raise RuntimeError(
            "TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY are required when "
            "PASSWORD_RESET_ENABLED=true and TURNSTILE_ENABLED=true."
        )


def validate_runtime_settings(application_settings: Settings) -> None:
    """Fail fast when production settings would expose the app unsafely."""

    uses_development_app_password = application_settings.app_password == DEVELOPMENT_APP_PASSWORD
    uses_development_secret = application_settings.app_secret_key == DEVELOPMENT_SECRET_KEY
    _validate_password_reset_settings(application_settings)
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


def _request_accepts_html(request: Request) -> bool:
    """Return whether the client is navigating as a browser page request."""

    accept_header = request.headers.get("accept", "")
    return "text/html" in accept_header.lower() or "application/xhtml+xml" in accept_header.lower()


def _apply_security_headers(response: Response, application_settings: Settings) -> Response:
    """Add defensive browser headers to a response before returning it."""

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    if application_settings.is_production:
        response.headers["Strict-Transport-Security"] = HSTS_HEADER_VALUE
    script_sources = "'self'"
    frame_sources = ""
    if application_settings.password_reset_enabled and application_settings.turnstile_enabled:
        script_sources = "'self' https://challenges.cloudflare.com"
        frame_sources = "frame-src https://challenges.cloudflare.com; "
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src {script_sources}; "
        "worker-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "media-src 'self' blob:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        f"{frame_sources}"
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return response


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Render app-styled browser errors while preserving JSON API errors."""

    if not _request_accepts_html(request):
        return await http_exception_handler(request, exc)

    status_code = int(exc.status_code)
    authenticated = current_username(request) is not None
    return templates.TemplateResponse(
        request,
        "error.html",
        template_context(
            request,
            error_code=status_code,
            error_title=HTML_ERROR_TITLES.get(status_code, "Request error"),
            error_message=HTML_ERROR_MESSAGES.get(status_code, "TicketPilot could not complete that request."),
            back_link_href="/work" if authenticated else "/login",
            back_link_label="Back to Work" if authenticated else "Back to Login",
        ),
        status_code=status_code,
        headers=getattr(exc, "headers", None),
    )


def _database_independent_path(path: str) -> bool:
    """Return whether a request can be served without database access."""

    return path in DATABASE_INDEPENDENT_PATHS or any(path.startswith(prefix) for prefix in DATABASE_INDEPENDENT_PREFIXES)


def _service_temporarily_unavailable_response(request: Request) -> Response:
    """Return a non-revealing temporary service page or JSON error."""

    application_settings = getattr(request.app.state, "application_settings", settings)
    headers = {
        "Cache-Control": "no-store",
        "Retry-After": str(SERVICE_UNAVAILABLE_RETRY_SECONDS),
    }
    if not _request_accepts_html(request):
        return _apply_security_headers(JSONResponse(
            {"detail": "Service temporarily unavailable."},
            status_code=503,
            headers=headers,
        ), application_settings)

    return _apply_security_headers(templates.TemplateResponse(
        request,
        "service_unavailable.html",
        {
            "request": request,
            "retry_seconds": SERVICE_UNAVAILABLE_RETRY_SECONDS,
            "retry_url": "/login",
            "static_asset_version": static_asset_version(),
        },
        status_code=503,
        headers=headers,
    ), application_settings)


async def _database_exception_handler(request: Request, exc: DBAPIError) -> Response:
    """Convert database outages into the same controlled temporary page."""

    database_monitor = getattr(request.app.state, "database_availability_monitor", None)
    if database_monitor is not None:
        database_monitor.mark_unavailable()
    return _service_temporarily_unavailable_response(request)


def create_app(
    application_settings: Settings = settings,
    database_availability_monitor: DatabaseAvailabilityMonitor | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    configure_logging(application_settings)
    validate_runtime_settings(application_settings)
    fastapi_app = FastAPI(title="Ticket Pilot for Autotask", docs_url=None, redoc_url=None, openapi_url=None)
    fastapi_app.state.application_settings = application_settings
    fastapi_app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    fastapi_app.add_exception_handler(OperationalError, _database_exception_handler)
    fastapi_app.add_exception_handler(DBAPIError, _database_exception_handler)
    fastapi_app.state.database_availability_monitor = (
        database_availability_monitor
        or DatabaseAvailabilityMonitor(migrations_pending=startup_migrations_are_pending())
    )

    fastapi_app.add_middleware(SessionTimeoutMiddleware, application_settings=application_settings)
    fastapi_app.add_middleware(
        SessionMiddleware,
        secret_key=application_settings.app_secret_key,
        session_cookie="ticket_pilot_session",
        https_only=application_settings.session_cookie_secure,
        same_site="lax",
        max_age=application_settings.session_timeout_seconds,
    )

    fastapi_app.mount("/static", StaticFiles(directory="ticket_pilot/static"), name="static")

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

    if application_settings.pushover_notifications_enabled:

        @fastapi_app.on_event("startup")
        async def start_app_health_notifications() -> None:
            """Start best-effort Pushover health notifications for this app process."""

            fastapi_app.state.app_health_notification_task = asyncio.create_task(
                app_health_notification_scheduler(application_settings)
            )

        @fastapi_app.on_event("shutdown")
        async def stop_app_health_notifications() -> None:
            """Stop the health notification task cleanly during application shutdown."""

            notification_task = getattr(fastapi_app.state, "app_health_notification_task", None)
            if notification_task is None:
                return

            notification_task.cancel()
            with suppress(asyncio.CancelledError):
                await notification_task

    @fastapi_app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Add defensive browser headers to every response."""

        response = await call_next(request)
        return _apply_security_headers(response, application_settings)

    @fastapi_app.middleware("http")
    async def require_database(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Serve a safe branded temporary page while the database is unavailable."""

        if _database_independent_path(request.url.path):
            return await call_next(request)

        database_monitor = request.app.state.database_availability_monitor
        database_is_available = await asyncio.to_thread(
            database_monitor.database_available,
            application_settings,
        )
        if not database_is_available:
            return _service_temporarily_unavailable_response(request)

        return await call_next(request)

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
    fastapi_app.include_router(password_reset.router)
    fastapi_app.include_router(passkeys.router)
    fastapi_app.include_router(mobile.router)
    fastapi_app.include_router(configuration.router)
    fastapi_app.include_router(users.router)
    fastapi_app.include_router(changelog.router)
    fastapi_app.include_router(help.router)
    fastapi_app.include_router(debug.router)
    fastapi_app.include_router(debug.legacy_router)
    fastapi_app.include_router(review.router)
    return fastapi_app


app = create_app()
