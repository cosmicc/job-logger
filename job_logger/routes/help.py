"""Authenticated help page and stateless help assistant endpoint."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.security import current_user_kind, require_authenticated_username, validate_csrf_header
from job_logger.services.changelog import current_changelog_entry, load_changelog_entries
from job_logger.services.help_assistant import (
    MAX_HELP_QUESTION_CHARS,
    HelpAssistantError,
    answer_help_question,
)
from job_logger.services.support_contact import append_help_contact_footer
from job_logger.ui import template_context, templates
from job_logger.version import APP_VERSION

router = APIRouter(prefix="/help", tags=["help"])
logger = logging.getLogger(__name__)


@router.get("", response_class=HTMLResponse)
def help_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Render the authenticated end-user help page."""

    try:
        require_authenticated_username(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    application_settings = getattr(request.app.state, "application_settings", settings)
    changelog_entries = load_changelog_entries()
    return templates.TemplateResponse(
        request,
        "help.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            ai_help_configured=application_settings.ai_help_configured,
            ai_help_max_question_chars=MAX_HELP_QUESTION_CHARS,
            changelog_entries=changelog_entries,
            current_changelog_entry=current_changelog_entry(changelog_entries),
        ),
    )


@router.post("/ask")
async def ask_help_question(request: Request) -> JSONResponse:
    """Answer one authenticated help question without storing it locally."""

    trace_id = uuid.uuid4().hex[:12]
    actor = "anonymous"
    user_kind = "unknown"
    try:
        actor = require_authenticated_username(request)
        user_kind = current_user_kind(request) or "unknown"
        validate_csrf_header(request)
    except HTTPException as exc:
        logger.warning(
            "AI Help request rejected trace_id=%s actor=%s user_kind=%s status_code=%s reason=%s",
            trace_id,
            actor,
            user_kind,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    try:
        payload: Any = await request.json()
    except ValueError:
        logger.warning(
            "AI Help request rejected trace_id=%s actor=%s user_kind=%s reason=invalid_json",
            trace_id,
            actor,
            user_kind,
        )
        return JSONResponse({"detail": "Invalid help request."}, status_code=status.HTTP_400_BAD_REQUEST)

    if not isinstance(payload, dict):
        logger.warning(
            "AI Help request rejected trace_id=%s actor=%s user_kind=%s reason=invalid_payload_type payload_type=%s",
            trace_id,
            actor,
            user_kind,
            type(payload).__name__,
        )
        return JSONResponse({"detail": "Invalid help request."}, status_code=status.HTTP_400_BAD_REQUEST)

    question = payload.get("question")
    if not isinstance(question, str):
        logger.warning(
            "AI Help request rejected trace_id=%s actor=%s user_kind=%s reason=missing_question",
            trace_id,
            actor,
            user_kind,
        )
        return JSONResponse({"detail": "Enter a help question first."}, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        application_settings = getattr(request.app.state, "application_settings", settings)
        logger.info(
            "AI Help request received trace_id=%s actor=%s user_kind=%s provider=%s configured=%s question_length=%s",
            trace_id,
            actor,
            user_kind,
            application_settings.ai_help_provider,
            application_settings.ai_help_configured,
            len(question),
        )
        logger.debug(
            "AI Help request settings trace_id=%s model=%s max_tokens=%s temperature=%s instructions_length=%s",
            trace_id,
            application_settings.gemini_model,
            application_settings.ai_help_max_tokens,
            application_settings.ai_help_temperature,
            len(application_settings.ai_help_instructions or ""),
        )
        result = answer_help_question(
            question=question,
            application_settings=application_settings,
            trace_id=trace_id,
        )
    except HelpAssistantError as exc:
        logger.error(
            "AI Help request failed trace_id=%s actor=%s user_kind=%s status_code=%s error_class=%s detail=%s",
            trace_id,
            actor,
            user_kind,
            status.HTTP_400_BAD_REQUEST,
            type(exc).__name__,
            str(exc),
        )
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception(
            "AI Help request crashed trace_id=%s actor=%s user_kind=%s",
            trace_id,
            actor,
            user_kind,
        )
        return JSONResponse(
            {"detail": "Help assistant request could not be completed."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    logger.info(
        "AI Help request completed trace_id=%s actor=%s user_kind=%s model=%s context_source_count=%s answer_length=%s",
        trace_id,
        actor,
        user_kind,
        result.model,
        result.context_source_count,
        len(result.answer_text),
    )

    answer_text = append_help_contact_footer(result.answer_text, application_settings)
    return JSONResponse(
        {
            "answer": answer_text,
            "model": result.model,
            "context_source_count": result.context_source_count,
        }
    )
