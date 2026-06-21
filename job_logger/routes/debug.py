"""Troubleshooting routes for Autotask and authentication diagnostics."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.logging_config import redact_sensitive_text
from job_logger.models import Job, SubmissionAttempt, WebUser
from job_logger.security import add_flash_message, require_super_admin, validate_csrf_token
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import AutotaskConnectivityResult, test_autotask_connectivity
from job_logger.services.backups import (
    BACKUP_MEDIA_TYPE,
    AutomaticBackupFile,
    BackupValidationError,
    create_full_backup,
    list_automatic_backup_files,
    read_automatic_backup_content,
    restore_full_backup,
)
from job_logger.services.login_failures import read_recent_login_failures
from job_logger.time_utils import format_local_display
from job_logger.ui import template_context, templates
from job_logger.version import APP_VERSION

logger = logging.getLogger(__name__)
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

    # job_owner_name is the display name of the managed web user who owns the job.
    job_owner_name: str | None

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

    # created_at_utc is the raw UTC timestamp kept for audit correlation.
    created_at_utc: str

    # created_at_display is the user-facing America/Detroit timestamp.
    created_at_display: str


@dataclass(frozen=True)
class DebugAutomaticBackup:
    """Automatic backup metadata rendered on the debug page."""

    filename: str
    created_at_display: str
    size_display: str


def _safe_autotask_config() -> dict[str, object]:
    """Return a redacted Autotask configuration summary for troubleshooting."""

    return {
        "provider": settings.autotask_provider,
        "base_url": settings.autotask_base_url,
        "has_username": bool(settings.autotask_username),
        "has_secret": bool(settings.autotask_secret),
        "has_api_integration_code": bool(settings.autotask_api_integration_code),
        "time_entry_role_source": "selected ticket assignedResourceroleID",
        "billing_code_source": "selected ticket inheritance",
        "time_entry_type": settings.autotask_time_entry_type,
        "status_id_map": settings.autotask_status_id_map,
        "max_attempt_rows": 200,
    }


def _serialize_connectivity_result(result: AutotaskConnectivityResult) -> dict[str, object]:
    """Return a session-safe Autotask connectivity result without secrets."""

    return {
        "provider": result.provider,
        "available": result.available,
        "summary": result.summary,
        "tips": list(result.tips),
        "checked_operations": list(result.checked_operations),
        "failed_operation": result.failed_operation,
    }


def _serialize_submission_attempt(
    attempt: SubmissionAttempt,
    job_ticket_number: str | None,
    job_owner_name: str | None,
) -> DebugSubmissionAttempt:
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
        job_owner_name=job_owner_name,
        provider=attempt.provider,
        succeeded=attempt.succeeded,
        external_id=attempt.external_id,
        safe_error=attempt.safe_error,
        request_snapshot=request_snapshot_text,
        created_at_utc=attempt.created_at_utc.isoformat(),
        created_at_display=format_local_display(attempt.created_at_utc),
    )


def _backup_upload_max_mb() -> int:
    """Return the configured restore upload limit rounded down to MiB."""

    return settings.max_backup_restore_bytes // (1024 * 1024)


def _format_file_size(size_bytes: int) -> str:
    """Return a compact human-readable file size for backup listings."""

    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _serialize_automatic_backup(backup_file: AutomaticBackupFile) -> DebugAutomaticBackup:
    """Return display-safe metadata for one automatic backup file."""

    return DebugAutomaticBackup(
        filename=backup_file.filename,
        created_at_display=format_local_display(backup_file.created_at_utc),
        size_display=_format_file_size(backup_file.size_bytes),
    )


def _redirect_anonymous_or_raise(exc: HTTPException) -> RedirectResponse:
    """Redirect anonymous users to login while preserving super-admin-only 403s."""

    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)

    raise exc


@router.get("", response_class=HTMLResponse)
def debug_page(request: Request, database_session: Session = Depends(get_database_session)) -> Response:
    """Render authenticated diagnostics, submission attempts, and login failures."""

    try:
        require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    attempt_rows = list(
        database_session.execute(
            select(SubmissionAttempt, Job.ticket_number, WebUser.full_name)
            .join(Job, SubmissionAttempt.job_id == Job.id, isouter=True)
            .join(WebUser, Job.web_user_id == WebUser.id, isouter=True)
            .order_by(desc(SubmissionAttempt.created_at_utc))
            .limit(200)
        ).all()
    )

    debug_submission_attempts = [
        _serialize_submission_attempt(attempt, job_ticket_number, job_owner_name)
        for attempt, job_ticket_number, job_owner_name in attempt_rows
    ]

    return templates.TemplateResponse(
        request,
        "debug.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            autotask_settings=_safe_autotask_config(),
            autotask_connectivity=request.session.get("autotask_connectivity_result"),
            login_failure_log_path=settings.login_failure_log_path,
            login_failure_debug_rows=settings.login_failure_debug_rows,
            login_failures=read_recent_login_failures(),
            submission_attempts=debug_submission_attempts,
            automatic_backups=[
                _serialize_automatic_backup(backup_file)
                for backup_file in list_automatic_backup_files(settings.automatic_backup_dir)
            ],
            automatic_backups_enabled=settings.automatic_backups_enabled,
            automatic_backup_dir=settings.automatic_backup_dir,
            backup_upload_max_mb=_backup_upload_max_mb(),
        ),
    )


@router.get("/logs/login-failures")
def download_login_failure_log(request: Request) -> Response:
    """Download the raw failed-login JSONL log for authenticated diagnostics."""

    try:
        require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    log_path = Path(settings.login_failure_log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Login failure log not found")

    return Response(
        content=redact_sensitive_text(log_path.read_text(encoding="utf-8", errors="replace")),
        media_type="application/jsonl; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="job-logger-login-failures.log"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/backup")
async def download_full_backup(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download a CSRF-protected full application data backup."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    backup = create_full_backup(database_session)
    record_audit_event(
        database_session,
        actor=actor,
        action="debug.full_backup.downloaded",
        request=request,
        details={
            "filename": backup.filename,
            "table_count": len(backup.table_counts),
            "total_rows": backup.total_rows,
            "table_counts": backup.table_counts,
        },
    )
    database_session.commit()
    logger.warning(
        "Created full Job Logger backup filename=%s total_rows=%s actor=%s",
        backup.filename,
        backup.total_rows,
        actor,
    )
    return Response(
        content=backup.content,
        media_type=BACKUP_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{backup.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/restore")
async def restore_full_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Restore a previously downloaded full application data backup."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    if str(form_data.get("confirmation", "")).strip() != "RESTORE":
        add_flash_message(request, "Type RESTORE to confirm full data restore.", "error")
        return RedirectResponse(url="/debug#full-backup", status_code=303)

    backup_file = form_data.get("backup_file")
    if not isinstance(backup_file, UploadFile):
        add_flash_message(request, "Choose a Job Logger backup file to restore.", "error")
        return RedirectResponse(url="/debug#full-backup", status_code=303)

    content = await backup_file.read(settings.max_backup_restore_bytes + 1)
    await backup_file.close()
    if len(content) > settings.max_backup_restore_bytes:
        add_flash_message(request, f"Backup file is larger than {_backup_upload_max_mb()} MB.", "error")
        return RedirectResponse(url="/debug#full-backup", status_code=303)

    try:
        summary = restore_full_backup(database_session, content)
    except BackupValidationError as exc:
        logger.warning("Rejected full Job Logger restore upload: %s", exc)
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/debug#full-backup", status_code=303)
    except Exception:
        logger.exception("Full Job Logger restore failed unexpectedly")
        add_flash_message(request, "Restore failed. Check the app log before trying again.", "error")
        return RedirectResponse(url="/debug#full-backup", status_code=303)

    record_audit_event(
        database_session,
        actor=actor,
        action="debug.full_backup.restored",
        request=request,
        details={
            "table_count": len(summary.table_counts),
            "total_rows": summary.total_rows,
            "table_counts": summary.table_counts,
        },
    )
    database_session.commit()
    add_flash_message(
        request,
        f"Full data restore completed. Restored {summary.total_rows} rows across {len(summary.table_counts)} tables.",
        "success",
    )
    return RedirectResponse(url="/debug#full-backup", status_code=303)


@router.post("/automatic-backups/restore")
async def restore_automatic_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Restore a retained automatic backup selected from the debug page."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    backup_filename = str(form_data.get("filename", "")).strip()
    if str(form_data.get("confirmation", "")).strip() != "RESTORE":
        add_flash_message(request, "Type RESTORE to confirm automatic backup restore.", "error")
        return RedirectResponse(url="/debug#automatic-backups", status_code=303)

    try:
        content = read_automatic_backup_content(
            settings.automatic_backup_dir,
            backup_filename,
            max_bytes=settings.max_backup_restore_bytes,
        )
        summary = restore_full_backup(database_session, content)
    except BackupValidationError as exc:
        logger.warning("Rejected automatic backup restore filename=%s error=%s", backup_filename, exc)
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/debug#automatic-backups", status_code=303)
    except Exception:
        logger.exception("Automatic Job Logger restore failed unexpectedly filename=%s", backup_filename)
        add_flash_message(request, "Restore failed. Check the app log before trying again.", "error")
        return RedirectResponse(url="/debug#automatic-backups", status_code=303)

    record_audit_event(
        database_session,
        actor=actor,
        action="debug.automatic_backup.restored",
        request=request,
        details={
            "filename": backup_filename,
            "table_count": len(summary.table_counts),
            "total_rows": summary.total_rows,
            "table_counts": summary.table_counts,
        },
    )
    database_session.commit()
    add_flash_message(
        request,
        f"Automatic backup restore completed. Restored {summary.total_rows} rows across {len(summary.table_counts)} tables.",
        "success",
    )
    return RedirectResponse(url="/debug#automatic-backups", status_code=303)


@router.post("/autotask/test")
async def test_autotask_api(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Test mandatory Autotask API connectivity from the debug page."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    connectivity_result = test_autotask_connectivity()
    request.session["autotask_connectivity_result"] = _serialize_connectivity_result(connectivity_result)
    record_audit_event(
        database_session,
        actor=actor,
        action="debug.autotask_api.tested",
        request=request,
        details={
            "provider": connectivity_result.provider,
            "available": connectivity_result.available,
            "checked_operations": list(connectivity_result.checked_operations),
            "tip_count": len(connectivity_result.tips),
        },
    )
    database_session.commit()
    if connectivity_result.available:
        add_flash_message(request, connectivity_result.summary, "success")
    else:
        add_flash_message(request, f"Autotask API is down and needs fixing. {connectivity_result.summary}", "error")

    return RedirectResponse(url="/debug", status_code=303)
