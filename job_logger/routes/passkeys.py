"""WebAuthn passkey routes for managed web-user login."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from job_logger.database import get_database_session
from job_logger.security import (
    PASSKEY_AUTH_METHOD,
    WEB_USER_SESSION_KIND,
    add_flash_message,
    current_user_kind,
    current_web_user_id,
    login_web_user_session,
    logout_session,
    require_authenticated_username,
    validate_csrf_header,
    validate_csrf_token,
)
from job_logger.services.audit import record_audit_event
from job_logger.services.login_failures import log_failed_login_attempt
from job_logger.services.passkeys import (
    PasskeyError,
    begin_passkey_authentication,
    begin_passkey_registration,
    delete_passkey_credential,
    finish_passkey_authentication,
    finish_passkey_registration,
)
from job_logger.services.users import WebUserError, get_enabled_web_user_by_id_or_raise

router = APIRouter(tags=["passkeys"])


async def _json_payload(request: Request) -> dict[str, Any]:
    """Return a JSON object body or raise a safe HTTP error."""

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must be a JSON object.")
    return payload


def _current_passkey_web_user(request: Request, database_session: Session):
    """Return the enabled managed web user allowed to manage passkeys."""

    require_authenticated_username(request)
    if current_user_kind(request) != WEB_USER_SESSION_KIND:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managed web-user passkeys are required.")
    try:
        return get_enabled_web_user_by_id_or_raise(database_session, current_web_user_id(request))
    except WebUserError:
        logout_session(request)
        raise


@router.post("/config/passkeys/options")
async def passkey_registration_options(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Return browser WebAuthn options for registering a passkey."""

    validate_csrf_header(request)
    try:
        web_user = _current_passkey_web_user(request, database_session)
        options = begin_passkey_registration(database_session, request, web_user)
    except WebUserError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_403_FORBIDDEN)
    except (HTTPException, PasskeyError) as exc:
        status_code = exc.status_code if isinstance(exc, HTTPException) else status.HTTP_400_BAD_REQUEST
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=status_code)

    return JSONResponse({"publicKey": options})


@router.post("/config/passkeys/verify")
async def passkey_registration_verify(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Verify and save a browser-created passkey for the current user."""

    validate_csrf_header(request)
    actor = "unknown"
    try:
        actor = require_authenticated_username(request)
        web_user = _current_passkey_web_user(request, database_session)
        credential_payload = await _json_payload(request)
        credential = finish_passkey_registration(database_session, request, web_user, credential_payload)
        record_audit_event(
            database_session,
            actor=actor,
            action="auth.passkey.registered",
            request=request,
            details={
                "web_user_id": web_user.id,
                "credential_row_id": credential.id,
                "device_type": credential.device_type,
                "backed_up": credential.backed_up,
            },
        )
        database_session.commit()
        return JSONResponse(
            {
                "registered": True,
                "message": "Passkey added.",
                "credential": {
                    "id": credential.id,
                    "device_type": credential.device_type,
                    "backed_up": credential.backed_up,
                },
            }
        )
    except (HTTPException, PasskeyError, WebUserError) as exc:
        database_session.rollback()
        record_audit_event(
            database_session,
            actor=actor,
            action="auth.passkey.registration_failed",
            request=request,
            details={"error": str(getattr(exc, "detail", exc))},
        )
        database_session.commit()
        status_code = exc.status_code if isinstance(exc, HTTPException) else status.HTTP_400_BAD_REQUEST
        return JSONResponse({"detail": str(getattr(exc, "detail", exc))}, status_code=status_code)


@router.post("/config/passkeys/{credential_row_id}/delete")
async def passkey_delete(
    credential_row_id: str,
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Delete a passkey registered to the current managed web user."""

    try:
        actor = require_authenticated_username(request)
        web_user = _current_passkey_web_user(request, database_session)
        form_data = await request.form()
        validate_csrf_token(request, str(form_data.get("csrf_token", "")))
        credential = delete_passkey_credential(
            database_session,
            web_user_id=web_user.id,
            credential_row_id=credential_row_id,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="auth.passkey.deleted",
            request=request,
            details={"web_user_id": web_user.id, "credential_row_id": credential.id},
        )
        database_session.commit()
        add_flash_message(request, "Passkey deleted.", "success")
    except HTTPException:
        database_session.rollback()
        raise
    except (PasskeyError, WebUserError) as exc:
        database_session.rollback()
        add_flash_message(request, str(getattr(exc, "detail", exc)), "error")

    return RedirectResponse(url="/config#passkeys", status_code=303)


@router.post("/login/passkey/options")
async def passkey_login_options(request: Request) -> JSONResponse:
    """Return browser WebAuthn options for passkey login."""

    validate_csrf_header(request)
    try:
        options = begin_passkey_authentication(request)
    except PasskeyError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    return JSONResponse({"publicKey": options})


@router.post("/login/passkey/verify")
async def passkey_login_verify(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> JSONResponse:
    """Verify a passkey assertion and create a managed-user session."""

    validate_csrf_header(request)
    try:
        credential_payload = await _json_payload(request)
        authentication = finish_passkey_authentication(database_session, request, credential_payload)
        web_user = authentication.web_user
        login_web_user_session(
            request,
            username=web_user.username,
            web_user_id=web_user.id,
            authentication_method=PASSKEY_AUTH_METHOD,
        )
        add_flash_message(request, "Signed in with passkey.", "success")
        record_audit_event(
            database_session,
            actor=web_user.username,
            action="auth.passkey.login.succeeded",
            request=request,
            details={
                "web_user_id": web_user.id,
                "credential_row_id": authentication.credential.id,
            },
        )
        database_session.commit()
        return JSONResponse({"authenticated": True, "redirect_url": "/home"})
    except (HTTPException, PasskeyError) as exc:
        database_session.rollback()
        record_audit_event(
            database_session,
            actor="passkey",
            action="auth.passkey.login.failed",
            request=request,
            details={"error": str(getattr(exc, "detail", exc))},
        )
        log_failed_login_attempt(
            request,
            submitted_username="passkey",
            submitted_password="",
            reason="passkey_failed",
        )
        database_session.commit()
        status_code = exc.status_code if isinstance(exc, HTTPException) else status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            {"detail": str(getattr(exc, "detail", exc)), "fallback": "password"},
            status_code=status_code,
        )
