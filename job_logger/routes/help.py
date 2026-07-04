"""Authenticated help page and stateless help assistant endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.security import require_authenticated_username, validate_csrf_header
from job_logger.services.help_assistant import (
    MAX_HELP_QUESTION_CHARS,
    HelpAssistantError,
    answer_help_question,
)
from job_logger.ui import template_context, templates
from job_logger.version import APP_VERSION

router = APIRouter(prefix="/help", tags=["help"])


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
    return templates.TemplateResponse(
        request,
        "help.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            ai_help_configured=application_settings.ai_help_configured,
            ai_help_max_question_chars=MAX_HELP_QUESTION_CHARS,
        ),
    )


@router.post("/ask")
async def ask_help_question(request: Request) -> JSONResponse:
    """Answer one authenticated help question without storing it locally."""

    try:
        require_authenticated_username(request)
        validate_csrf_header(request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    try:
        payload: Any = await request.json()
    except ValueError:
        return JSONResponse({"detail": "Invalid help request."}, status_code=status.HTTP_400_BAD_REQUEST)

    if not isinstance(payload, dict):
        return JSONResponse({"detail": "Invalid help request."}, status_code=status.HTTP_400_BAD_REQUEST)

    question = payload.get("question")
    if not isinstance(question, str):
        return JSONResponse({"detail": "Enter a help question first."}, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        application_settings = getattr(request.app.state, "application_settings", settings)
        result = answer_help_question(question=question, application_settings=application_settings)
    except HelpAssistantError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)

    return JSONResponse(
        {
            "answer": result.answer_text,
            "model": result.model,
            "context_source_count": result.context_source_count,
        }
    )
