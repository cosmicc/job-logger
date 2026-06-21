"""Middleware for enforcing local application session lifetime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from job_logger import database
from job_logger.config import Settings
from job_logger.security import expire_authenticated_session_if_needed
from job_logger.services.session_control import expire_invalid_web_user_session_if_needed


class SessionTimeoutMiddleware(BaseHTTPMiddleware):
    """Clear authenticated session state after the configured timeout expires."""

    def __init__(
        self,
        app: Callable[[Request], Awaitable[Response]],
        *,
        application_settings: Settings,
    ) -> None:
        """Store immutable settings used for every request timeout check."""

        super().__init__(app)
        self._application_settings = application_settings

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Expire stale authenticated sessions before the endpoint runs."""

        if not expire_authenticated_session_if_needed(request, self._application_settings):
            with database.SessionLocal() as database_session:
                expire_invalid_web_user_session_if_needed(request, database_session)
        return await call_next(request)
