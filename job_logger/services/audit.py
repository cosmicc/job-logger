"""Immutable audit logging service."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from job_logger.models import AuditEvent
from job_logger.security import sanitize_for_audit
from job_logger.services.login_failures import enforcement_client_ip_from_request


def _client_ip_from_request(request: Request | None) -> str | None:
    """Return the same trusted client IP used by login enforcement."""

    if request is None:
        return None

    return enforcement_client_ip_from_request(request)


def _user_agent_from_request(request: Request | None) -> str | None:
    """Return a bounded user agent string for troubleshooting."""

    if request is None:
        return None

    user_agent = request.headers.get("user-agent")
    if not user_agent:
        return None

    return user_agent[:255]


def record_audit_event(
    database_session: Session,
    *,
    actor: str,
    action: str,
    job_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an immutable audit event to the current database transaction."""

    audit_event = AuditEvent(
        actor=actor,
        action=action,
        job_id=job_id,
        details=sanitize_for_audit(details or {}),
        ip_address=_client_ip_from_request(request),
        user_agent=_user_agent_from_request(request),
    )
    database_session.add(audit_event)
    return audit_event
