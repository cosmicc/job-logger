"""Server-side controls for invalidating signed managed-user sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from job_logger.models import WebUser
from job_logger.security import (
    WEB_USER_SESSION_KIND,
    add_flash_message,
    authenticated_at_utc_from_session,
    current_user_kind_from_session,
    current_web_user_id_from_session,
    logout_session,
)
from job_logger.time_utils import ensure_utc, now_utc


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
