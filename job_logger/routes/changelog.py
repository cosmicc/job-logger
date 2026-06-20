"""Authenticated changelog route for source-controlled release notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.security import require_authenticated_username
from job_logger.services.changelog import current_changelog_entry, load_changelog_entries
from job_logger.ui import template_context, templates
from job_logger.version import APP_VERSION

router = APIRouter(tags=["changelog"])


@router.get("/changelog", response_class=HTMLResponse)
def changelog_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the authenticated release-history page."""

    try:
        require_authenticated_username(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    entries = load_changelog_entries()
    return templates.TemplateResponse(
        request,
        "changelog.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            changelog_entries=entries,
            current_changelog_entry=current_changelog_entry(entries),
        ),
    )
