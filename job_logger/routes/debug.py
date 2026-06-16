"""Troubleshooting routes for Autotask provider connectivity diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.models import Job, SubmissionAttempt
from job_logger.security import require_authenticated_username
from job_logger.ui import template_context, templates

router = APIRouter(prefix="/debug", tags=["debug"])


@dataclass(frozen=True)
class DebugSubmissionAttempt:
    """Sanitized submission attempt row for the debug interface."""

    # id is the immutable unique attempt identifier.
    id: str

    # job_id is the related local job UUID if the attempt belongs to a job.
    job_id: str

    # job_ticket_number is the optional ticket number on the related job.
    job_ticket_number: str | None

    # provider identifies mock or live Autotask mode for this attempt.
    provider: str

    # succeeded indicates whether this specific attempt was accepted.
    succeeded: bool

    # external_id stores the remote Autotask identifier when returned.
    external_id: str | None

    # safe_error keeps sanitized failure detail safe for UI.
    safe_error: str | None

    # request_snapshot contains a redacted request payload for troubleshooting.
    request_snapshot: str

    # created_at_utc is the UTC timestamp used for sorting and audit correlation.
    created_at_utc: str


def _safe_autotask_config() -> dict[str, object]:
    """Return a redacted Autotask configuration summary for troubleshooting."""

    return {
        "provider": settings.autotask_provider,
        "base_url": settings.autotask_base_url,
        "has_username": bool(settings.autotask_username),
        "has_secret": bool(settings.autotask_secret),
        "has_api_integration_code": bool(settings.autotask_api_integration_code),
        "has_resource_id": settings.autotask_resource_id is not None,
        "has_role_id": settings.autotask_role_id is not None,
        "time_entry_type": settings.autotask_time_entry_type,
        "status_id_map": settings.autotask_status_id_map,
        "max_attempt_rows": 200,
    }


def _serialize_submission_attempt(attempt: SubmissionAttempt, job_ticket_number: str | None) -> DebugSubmissionAttempt:
    """Return a UI-safe representation of one submission attempt."""

    request_snapshot_text = "{}"
    try:
        request_snapshot_text = json.dumps(attempt.request_snapshot, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        request_snapshot_text = "unserializable request_snapshot"

    return DebugSubmissionAttempt(
        id=attempt.id,
        job_id=attempt.job_id,
        job_ticket_number=job_ticket_number,
        provider=attempt.provider,
        succeeded=attempt.succeeded,
        external_id=attempt.external_id,
        safe_error=attempt.safe_error,
        request_snapshot=request_snapshot_text,
        created_at_utc=attempt.created_at_utc.isoformat(),
    )


@router.get("", response_class=HTMLResponse)
def debug_page(request: Request, database_session: Session = Depends(get_database_session)) -> Response:
    """Render the Autotask connection and submission logs page."""

    try:
        require_authenticated_username(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    attempt_rows = list(
        database_session.execute(
            select(SubmissionAttempt, Job.ticket_number)
            .join(Job, SubmissionAttempt.job_id == Job.id, isouter=True)
            .order_by(desc(SubmissionAttempt.created_at_utc))
            .limit(200)
        ).all()
    )

    debug_submission_attempts = [
        _serialize_submission_attempt(attempt, job_ticket_number)
        for attempt, job_ticket_number in attempt_rows
    ]

    return templates.TemplateResponse(
        request,
        "debug.html",
        template_context(
            request,
            autotask_settings=_safe_autotask_config(),
            submission_attempts=debug_submission_attempts,
        ),
    )
