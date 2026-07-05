"""Server-side controls for invalidating signed managed-user sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from job_logger.models import WebUser
from job_logger.security import (
    SESSION_PASSWORD_CHANGE_REQUIRED_KEY,
    WEB_USER_SESSION_KIND,
    add_flash_message,
    authenticated_at_utc_from_session,
    current_user_kind_from_session,
    current_web_user_id_from_session,
    logout_session,
)
from job_logger.time_utils import ensure_utc, now_utc

PASSWORD_CHANGE_ALLOWED_REQUESTS = {
    ("GET", "/config"),
    ("POST", "/config/password"),
    ("POST", "/logout"),
}


@dataclass(frozen=True)
class WebUserSessionInvalidationResult:
    """Summary returned after forcing managed web users to sign in again."""

    invalidated_at_utc: datetime
    affected_user_count: int


def invalidate_web_user_sessions(
    user: WebUser,
    *,
    invalidated_at_utc: datetime | None = None,
) -> None:
    """Set the per-user UTC cutoff that makes existing signed sessions stale."""

    user.sessions_invalidated_at_utc = ensure_utc(invalidated_at_utc or now_utc())


def invalidate_all_web_user_sessions(
    database_session: Session,
    *,
    invalidated_at_utc: datetime | None = None,
) -> WebUserSessionInvalidationResult:
    """Force every managed web user to authenticate again while leaving super admin alone."""

    cutoff = ensure_utc(invalidated_at_utc or now_utc())
    result = database_session.execute(
        update(WebUser).values(sessions_invalidated_at_utc=cutoff)
    )
    return WebUserSessionInvalidationResult(
        invalidated_at_utc=cutoff,
        affected_user_count=int(result.rowcount or 0),
    )


def expire_invalid_web_user_session_if_needed(
    request: Request,
    database_session: Session,
) -> bool:
    """Clear signed managed-user sessions that are disabled, deleted, or too old."""

    if current_user_kind_from_session(request.session) != WEB_USER_SESSION_KIND:
        return False

    web_user_id = current_web_user_id_from_session(request.session)
    web_user = database_session.get(WebUser, web_user_id) if web_user_id else None
    if web_user is None or web_user.disabled:
        logout_session(request)
        add_flash_message(
            request,
            "This user account is disabled. Contact the administrator.",
            "error",
        )
        return True

    authenticated_at = authenticated_at_utc_from_session(request.session)
    if authenticated_at is None:
        logout_session(request)
        add_flash_message(request, "Session expired. Sign in again.", "error")
        return True

    if web_user.sessions_invalidated_at_utc is None:
        return False

    invalidated_at = ensure_utc(web_user.sessions_invalidated_at_utc)
    if authenticated_at <= invalidated_at:
        logout_session(request)
        add_flash_message(
            request,
            "Your session was signed out by an administrator. Sign in again.",
            "error",
        )
        return True

    return False


def _browser_expects_html(request: Request) -> bool:
    """Return whether the current request is a browser navigation/form request."""

    accept_header = request.headers.get("accept", "").lower()
    return request.method.upper() == "GET" or "text/html" in accept_header or "application/xhtml+xml" in accept_header


def enforce_required_password_change_if_needed(
    request: Request,
    database_session: Session,
) -> Response | None:
    """Return a blocking response when a managed user must replace a temporary password."""

    if current_user_kind_from_session(request.session) != WEB_USER_SESSION_KIND:
        return None

    web_user_id = current_web_user_id_from_session(request.session)
    web_user = database_session.get(WebUser, web_user_id) if web_user_id else None
    if web_user is None or web_user.disabled:
        return None

    password_change_required = bool(
        request.session.get(SESSION_PASSWORD_CHANGE_REQUIRED_KEY)
        or web_user.password_must_change
    )
    if not password_change_required:
        request.session.pop(SESSION_PASSWORD_CHANGE_REQUIRED_KEY, None)
        return None

    request.session[SESSION_PASSWORD_CHANGE_REQUIRED_KEY] = True
    if (request.method.upper(), request.url.path) in PASSWORD_CHANGE_ALLOWED_REQUESTS:
        return None

    if _browser_expects_html(request):
        add_flash_message(request, "Change your temporary password before using Job Logger.", "error")
        return RedirectResponse(url="/config?password_required=1", status_code=303)

    return JSONResponse({"detail": "Password change required."}, status_code=403)
