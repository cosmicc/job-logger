"""Troubleshooting routes for Autotask and authentication diagnostics."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from ticket_pilot.config import settings
from ticket_pilot.database import get_database_session
from ticket_pilot.models import AuditEvent, CloudflareIPBlock, Job, LoginAttempt, SubmissionAttempt, WebUser
from ticket_pilot.security import add_flash_message, require_debug_access, validate_csrf_token
from ticket_pilot.services.audit import record_audit_event
from ticket_pilot.services.autotask import AutotaskConnectivityResult, test_autotask_connectivity
from ticket_pilot.services.backups import (
    AUTOMATIC_BACKUP_FILENAME_PREFIX,
    AUTOMATIC_BACKUP_FILENAME_SUFFIX,
    BACKUP_MEDIA_TYPE,
    AutomaticBackupFile,
    BackupValidationError,
    create_full_backup,
    list_automatic_backup_files,
    read_automatic_backup_content,
    restore_full_backup,
)
from ticket_pilot.services.cloudflare_blocks import (
    CloudflareBlockError,
    cloudflare_block_for_ip,
    cloudflare_ip_blocking_configured,
    create_app_cloudflare_block,
    ip_is_allowlisted,
    normalize_ip_address,
    remove_app_cloudflare_block,
    sanitize_cloudflare_block_reason,
)
from ticket_pilot.services.database_diagnostics import collect_database_diagnostics_snapshot
from ticket_pilot.services.login_failures import login_attempts_jsonl, read_login_failures_page, read_login_successes_page
from ticket_pilot.services.session_control import invalidate_all_web_user_sessions
from ticket_pilot.services.system_health import _format_file_size, collect_app_health_snapshot
from ticket_pilot.services.system_health import collect_disk_usage_snapshot as _collect_disk_usage_snapshot
from ticket_pilot.time_utils import format_local_display
from ticket_pilot.ui import template_context, templates
from ticket_pilot.version import APP_VERSION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])
legacy_router = APIRouter(prefix="/debug", tags=["diagnostics"])
DIAGNOSTIC_TABLE_PAGE_SIZE = 10
LOGIN_ATTEMPT_PAGE_SIZE = 7
CLOUDFLARE_BLOCK_PAGE_SIZE = DIAGNOSTIC_TABLE_PAGE_SIZE
SUBMISSION_ATTEMPT_PAGE_SIZE = 7
AUTOMATIC_BACKUP_TRIGGER_LABELS = {
    "startup": "Startup",
    "scheduled": "Hourly",
}
DEBUG_REDIRECT_FRAGMENTS = {
    "login-failures",
    "cloudflare-blocked-ips",
}


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
class DebugSubmissionAttemptPage:
    """One bounded page of sanitized Autotask submission attempts."""

    records: list[DebugSubmissionAttempt]
    page: int
    page_size: int
    total_records: int
    total_pages: int
    previous_page: int | None
    next_page: int | None


@dataclass(frozen=True)
class DebugAutomaticBackup:
    """Automatic backup metadata rendered on the debug page."""

    filename: str
    display_filename: str
    created_at_display: str
    size_display: str
    trigger_label: str | None


@dataclass(frozen=True)
class DebugCloudflareBlock:
    """Display-safe app-managed Cloudflare block row."""

    ip_address: str
    cloudflare_rule_id: str
    source: str
    reason: str
    failure_count: int | None
    created_at_display: str


@dataclass(frozen=True)
class DebugCloudflareBlockPage:
    """One bounded page of app-managed Cloudflare IP block rows."""

    records: list[DebugCloudflareBlock]
    page: int
    page_size: int
    total_records: int
    total_pages: int
    previous_page: int | None
    next_page: int | None


def _safe_autotask_config() -> dict[str, object]:
    """Return a redacted Autotask configuration summary for troubleshooting."""

    return {
        "provider": settings.autotask_provider,
        "base_url": settings.autotask_base_url,
        "has_username": bool(settings.autotask_username),
        "has_secret": bool(settings.autotask_secret),
        "has_api_integration_code": bool(settings.autotask_api_integration_code),
        "time_entry_role_source": "Ticket role, ticket-assigned resource role, then managed-user default",
        "billing_code_source": "Ticket Work Type inheritance",
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


def _short_automatic_backup_filename(filename: str) -> str:
    """Return a compact display label while preserving the full backup filename."""

    return filename.removeprefix(AUTOMATIC_BACKUP_FILENAME_PREFIX).removesuffix(AUTOMATIC_BACKUP_FILENAME_SUFFIX)


def _automatic_backup_trigger_labels(
    database_session: Session,
    backup_files: tuple[AutomaticBackupFile, ...],
) -> dict[str, str]:
    """Return display labels for automatic backup triggers stored in audit details."""

    backup_filenames = {backup_file.filename for backup_file in backup_files}
    if not backup_filenames:
        return {}

    trigger_labels: dict[str, str] = {}
    events = database_session.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "debug.automatic_backup.created")
        .order_by(desc(AuditEvent.created_at_utc))
        .limit(500)
    )
    for event in events:
        if len(trigger_labels) == len(backup_filenames):
            break
        if not isinstance(event.details, dict):
            continue
        filename = str(event.details.get("filename") or "").strip()
        if filename not in backup_filenames or filename in trigger_labels:
            continue
        trigger = str(event.details.get("trigger") or "").strip().lower()
        label = AUTOMATIC_BACKUP_TRIGGER_LABELS.get(trigger)
        if label is not None:
            trigger_labels[filename] = label

    return trigger_labels


def _serialize_automatic_backup(
    backup_file: AutomaticBackupFile,
    *,
    trigger_label: str | None = None,
) -> DebugAutomaticBackup:
    """Return display-safe metadata for one automatic backup file."""

    return DebugAutomaticBackup(
        filename=backup_file.filename,
        display_filename=_short_automatic_backup_filename(backup_file.filename),
        created_at_display=format_local_display(backup_file.created_at_utc),
        size_display=_format_file_size(backup_file.size_bytes),
        trigger_label=trigger_label,
    )


def _paginate_cloudflare_blocks(
    records: list[CloudflareIPBlock],
    *,
    page: int,
    page_size: int,
) -> DebugCloudflareBlockPage:
    """Return one bounded page of app-managed Cloudflare block rows."""

    bounded_page_size = max(1, min(page_size, 100))
    total_records = len(records)
    total_pages = max(1, (total_records + bounded_page_size - 1) // bounded_page_size)
    bounded_page = max(1, min(page, total_pages))
    start_index = (bounded_page - 1) * bounded_page_size
    return DebugCloudflareBlockPage(
        records=[
            DebugCloudflareBlock(
                ip_address=block.ip_address,
                cloudflare_rule_id=block.cloudflare_rule_id,
                source=block.source,
                reason=block.reason,
                failure_count=block.failure_count,
                created_at_display=format_local_display(block.created_at_utc),
            )
            for block in records[start_index : start_index + bounded_page_size]
        ],
        page=bounded_page,
        page_size=bounded_page_size,
        total_records=total_records,
        total_pages=total_pages,
        previous_page=bounded_page - 1 if bounded_page > 1 else None,
        next_page=bounded_page + 1 if bounded_page < total_pages else None,
    )


def _paginate_submission_attempts(
    database_session: Session,
    *,
    page: int,
    page_size: int,
) -> DebugSubmissionAttemptPage:
    """Return one bounded page of newest Autotask submission attempts."""

    bounded_page_size = max(1, min(page_size, 100))
    total_records = database_session.scalar(select(func.count(SubmissionAttempt.id))) or 0
    total_pages = max(1, (total_records + bounded_page_size - 1) // bounded_page_size)
    bounded_page = max(1, min(page, total_pages))
    attempt_rows = list(
        database_session.execute(
            select(SubmissionAttempt, Job.ticket_number, WebUser.full_name)
            .join(Job, SubmissionAttempt.job_id == Job.id, isouter=True)
            .join(WebUser, Job.web_user_id == WebUser.id, isouter=True)
            .order_by(desc(SubmissionAttempt.created_at_utc))
            .offset((bounded_page - 1) * bounded_page_size)
            .limit(bounded_page_size)
        ).all()
    )

    return DebugSubmissionAttemptPage(
        records=[
            _serialize_submission_attempt(attempt, job_ticket_number, job_owner_name)
            for attempt, job_ticket_number, job_owner_name in attempt_rows
        ],
        page=bounded_page,
        page_size=bounded_page_size,
        total_records=total_records,
        total_pages=total_pages,
        previous_page=bounded_page - 1 if bounded_page > 1 else None,
        next_page=bounded_page + 1 if bounded_page < total_pages else None,
    )


def _redirect_anonymous_or_raise(exc: HTTPException) -> RedirectResponse:
    """Redirect anonymous users to login while preserving diagnostics 403s."""

    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)

    raise exc


def _debug_redirect(fragment: str) -> RedirectResponse:
    """Redirect back to one diagnostics section after a state-changing action."""

    return RedirectResponse(url=f"/diagnostics#{fragment}", status_code=303)


@legacy_router.get("", include_in_schema=False)
def legacy_diagnostics_page_redirect(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Redirect old Diagnostics bookmarks to the canonical namespace."""

    try:
        require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    query_string = request.url.query
    redirect_url = "/diagnostics"
    if query_string:
        redirect_url = f"{redirect_url}?{query_string}"
    return RedirectResponse(url=redirect_url, status_code=308)


def _debug_redirect_fragment_from_form(value: object, *, default: str) -> str:
    """Return a known diagnostics fragment from submitted form data."""

    fragment = str(value or "").strip()
    if fragment in DEBUG_REDIRECT_FRAGMENTS:
        return fragment
    return default


@router.get("", response_class=HTMLResponse)
def debug_page(
    request: Request,
    database_session: Session = Depends(get_database_session),
    success_page: int = Query(1, ge=1),
    failure_page: int = Query(1, ge=1),
    cloudflare_blocks_page: int = Query(1, ge=1),
    attempt_page: int = Query(1, ge=1),
) -> Response:
    """Render authenticated diagnostics, submission attempts, and login failures."""

    try:
        require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    submission_attempts_page = _paginate_submission_attempts(
        database_session,
        page=attempt_page,
        page_size=SUBMISSION_ATTEMPT_PAGE_SIZE,
    )
    login_failures = read_login_failures_page(
        database_session,
        page=failure_page,
        page_size=LOGIN_ATTEMPT_PAGE_SIZE,
    )
    all_cloudflare_ip_blocks = list(
        database_session.scalars(
            select(CloudflareIPBlock).order_by(desc(CloudflareIPBlock.created_at_utc))
        )
    )
    cloudflare_ip_blocks_page = _paginate_cloudflare_blocks(
        all_cloudflare_ip_blocks,
        page=cloudflare_blocks_page,
        page_size=CLOUDFLARE_BLOCK_PAGE_SIZE,
    )
    blocked_ip_addresses = {block.ip_address for block in all_cloudflare_ip_blocks}
    login_failure_ip_statuses = {}
    for failure in login_failures.records:
        normalized_ip = normalize_ip_address(failure.enforcement_client_ip)
        login_failure_ip_statuses[failure.entry_id] = {
            "ip_address": normalized_ip or failure.enforcement_client_ip,
            "valid": normalized_ip is not None,
            "blocked": normalized_ip in blocked_ip_addresses if normalized_ip else False,
            "allowlisted": ip_is_allowlisted(normalized_ip) if normalized_ip else False,
        }

    automatic_backup_files = list_automatic_backup_files(settings.automatic_backup_dir)
    automatic_backup_trigger_labels = _automatic_backup_trigger_labels(database_session, automatic_backup_files)
    disk_usage = _collect_disk_usage_snapshot()
    database_diagnostics = collect_database_diagnostics_snapshot()
    app_health_snapshot = collect_app_health_snapshot(
        database_session=database_session,
        disk_usage=disk_usage,
        database_snapshot=database_diagnostics,
    )

    return templates.TemplateResponse(
        request,
        "debug.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            autotask_settings=_safe_autotask_config(),
            autotask_connectivity=request.session.get("autotask_connectivity_result"),
            login_attempt_page_size=LOGIN_ATTEMPT_PAGE_SIZE,
            login_successes=read_login_successes_page(database_session, page=success_page, page_size=LOGIN_ATTEMPT_PAGE_SIZE),
            login_failures=login_failures,
            login_failure_ip_statuses=login_failure_ip_statuses,
            cloudflare_ip_blocks=cloudflare_ip_blocks_page.records,
            cloudflare_ip_blocks_page=cloudflare_ip_blocks_page,
            cloudflare_ip_blocking_configured=cloudflare_ip_blocking_configured(),
            app_health_snapshot=app_health_snapshot,
            app_health_degraded=app_health_snapshot.degraded,
            app_health_alert_label=app_health_snapshot.alert_label,
            disk_usage=disk_usage,
            database_diagnostics=database_diagnostics,
            submission_attempts=submission_attempts_page.records,
            submission_attempts_page=submission_attempts_page,
            submission_attempt_page_size=SUBMISSION_ATTEMPT_PAGE_SIZE,
            automatic_backups=[
                _serialize_automatic_backup(
                    backup_file,
                    trigger_label=automatic_backup_trigger_labels.get(backup_file.filename),
                )
                for backup_file in automatic_backup_files
            ],
            automatic_backups_enabled=settings.automatic_backups_enabled,
            automatic_backup_dir=settings.automatic_backup_dir,
            backup_upload_max_mb=_backup_upload_max_mb(),
        ),
    )


@router.get("/logs/login-failures")
@legacy_router.get("/logs/login-failures", include_in_schema=False)
def download_login_failure_log(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download failed-login rows as generated JSONL from the database."""

    try:
        require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    return Response(
        content=login_attempts_jsonl(database_session, succeeded=False),
        media_type="application/jsonl; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ticket-pilot-login-failures.jsonl"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/logs/login-successes")
@legacy_router.get("/logs/login-successes", include_in_schema=False)
def download_login_success_log(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download successful-login rows as generated JSONL from the database."""

    try:
        require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    return Response(
        content=login_attempts_jsonl(database_session, succeeded=True),
        media_type="application/jsonl; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ticket-pilot-login-successes.jsonl"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/login-failures/hide")
@legacy_router.post("/login-failures/hide", include_in_schema=False)
async def hide_login_failure_entry(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Hide one failed-login row from Diagnostics without deleting its database history."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    cleaned_entry_id = str(form_data.get("entry_id", "")).strip()
    if not re.fullmatch(r"[a-f0-9-]{36}", cleaned_entry_id):
        raise HTTPException(status_code=400, detail="Invalid failed-login entry ID.")

    login_attempt = database_session.scalar(
        select(LoginAttempt)
        .where(LoginAttempt.id == cleaned_entry_id, LoginAttempt.succeeded.is_(False))
        .limit(1)
    )
    if login_attempt is None:
        raise HTTPException(status_code=404, detail="Failed-login row not found.")
    if login_attempt.hidden_at_utc is None:
        login_attempt.hidden_at_utc = datetime.now(UTC)
        record_audit_event(
            database_session,
            actor=actor,
            action="debug.login_failure.hidden",
            request=request,
            details={
                "entry_id": cleaned_entry_id,
                "client_ip": login_attempt.client_ip,
            },
        )
        database_session.commit()
        add_flash_message(request, "Failed-login row hidden from Diagnostics.", "success")
    else:
        add_flash_message(request, "Failed-login row is already hidden.", "info")
    return _debug_redirect("login-failures")


@router.post("/cloudflare-blocks/block")
@legacy_router.post("/cloudflare-blocks/block", include_in_schema=False)
async def block_login_ip_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Create an app-managed Cloudflare block for a failed-login IP."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    redirect_fragment = _debug_redirect_fragment_from_form(
        form_data.get("redirect_fragment"),
        default="login-failures",
    )
    ip_address = str(form_data.get("ip_address", "")).strip()
    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        add_flash_message(request, "Cannot block an invalid IP address.", "error")
        return _debug_redirect(redirect_fragment)

    existing_block = cloudflare_block_for_ip(database_session, normalized_ip)
    if existing_block is not None:
        add_flash_message(request, "Cloudflare IP block is already active.", "info")
        return _debug_redirect(redirect_fragment)

    block_reason = sanitize_cloudflare_block_reason(
        form_data.get("reason"),
        default_reason="Diagnostics manual Cloudflare block",
    )

    try:
        block = create_app_cloudflare_block(
            database_session,
            normalized_ip,
            source="manual",
            reason=block_reason,
        )
        record_audit_event(
            database_session,
            actor=actor,
            action="debug.cloudflare_ip_block.created",
            request=request,
            details={
                "ip_address": block.ip_address,
                "cloudflare_rule_id": block.cloudflare_rule_id,
                "source": block.source,
                "reason": block.reason,
            },
        )
        database_session.commit()
    except CloudflareBlockError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")
        return _debug_redirect(redirect_fragment)

    add_flash_message(request, "Cloudflare IP block is active.", "success")
    return _debug_redirect(redirect_fragment)


@router.post("/cloudflare-blocks/unblock")
@legacy_router.post("/cloudflare-blocks/unblock", include_in_schema=False)
async def unblock_login_ip_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Remove one app-managed Cloudflare block and its local block-list row."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    ip_address = str(form_data.get("ip_address", "")).strip()
    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        add_flash_message(request, "Cannot unblock an invalid IP address.", "error")
        return _debug_redirect("cloudflare-blocked-ips")

    block = cloudflare_block_for_ip(database_session, normalized_ip)
    if block is None:
        add_flash_message(request, "IP address is not in the app-managed block list.", "info")
        return _debug_redirect("cloudflare-blocked-ips")

    cloudflare_rule_id = block.cloudflare_rule_id
    try:
        remove_app_cloudflare_block(database_session, block)
        record_audit_event(
            database_session,
            actor=actor,
            action="debug.cloudflare_ip_block.removed",
            request=request,
            details={
                "ip_address": normalized_ip,
                "cloudflare_rule_id": cloudflare_rule_id,
            },
        )
        database_session.commit()
    except CloudflareBlockError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")
        return _debug_redirect("cloudflare-blocked-ips")

    add_flash_message(request, "Cloudflare IP block was removed.", "success")
    return _debug_redirect("cloudflare-blocked-ips")


@router.post("/backup")
@legacy_router.post("/backup", include_in_schema=False)
async def download_full_backup(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download a CSRF-protected full application data backup."""

    try:
        actor = require_debug_access(request, database_session)
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
        "Created full TicketPilot backup filename=%s total_rows=%s actor=%s",
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
@legacy_router.post("/restore", include_in_schema=False)
async def restore_full_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Restore a previously downloaded full application data backup."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    if str(form_data.get("confirmation", "")).strip() != "RESTORE":
        add_flash_message(request, "Type RESTORE to confirm full data restore.", "error")
        return RedirectResponse(url="/diagnostics#full-backup", status_code=303)

    backup_file = form_data.get("backup_file")
    if not isinstance(backup_file, UploadFile):
        add_flash_message(request, "Choose a TicketPilot backup file to restore.", "error")
        return RedirectResponse(url="/diagnostics#full-backup", status_code=303)

    content = await backup_file.read(settings.max_backup_restore_bytes + 1)
    await backup_file.close()
    if len(content) > settings.max_backup_restore_bytes:
        add_flash_message(request, f"Backup file is larger than {_backup_upload_max_mb()} MB.", "error")
        return RedirectResponse(url="/diagnostics#full-backup", status_code=303)

    try:
        summary = restore_full_backup(database_session, content)
    except BackupValidationError as exc:
        logger.warning("Rejected full TicketPilot restore upload: %s", exc)
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/diagnostics#full-backup", status_code=303)
    except Exception:
        logger.exception("Full TicketPilot restore failed unexpectedly")
        add_flash_message(request, "Restore failed. Check the service logs before trying again.", "error")
        return RedirectResponse(url="/diagnostics#full-backup", status_code=303)

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
    return RedirectResponse(url="/diagnostics#full-backup", status_code=303)


@router.post("/automatic-backups/restore")
@legacy_router.post("/automatic-backups/restore", include_in_schema=False)
async def restore_automatic_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Restore a retained automatic backup selected from the debug page."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    backup_filename = str(form_data.get("filename", "")).strip()
    if str(form_data.get("confirmation", "")).strip() != "RESTORE":
        add_flash_message(request, "Type RESTORE to confirm automatic backup restore.", "error")
        return RedirectResponse(url="/diagnostics#automatic-backups", status_code=303)

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
        return RedirectResponse(url="/diagnostics#automatic-backups", status_code=303)
    except Exception:
        logger.exception("Automatic TicketPilot restore failed unexpectedly filename=%s", backup_filename)
        add_flash_message(request, "Restore failed. Check the service logs before trying again.", "error")
        return RedirectResponse(url="/diagnostics#automatic-backups", status_code=303)

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
    return RedirectResponse(url="/diagnostics#automatic-backups", status_code=303)


@router.post("/automatic-backups/download")
@legacy_router.post("/automatic-backups/download", include_in_schema=False)
async def download_automatic_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download one retained automatic backup after strict filename validation."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    backup_filename = str(form_data.get("filename", "")).strip()

    try:
        content = read_automatic_backup_content(
            settings.automatic_backup_dir,
            backup_filename,
            max_bytes=settings.max_backup_restore_bytes,
        )
    except BackupValidationError as exc:
        logger.warning("Rejected automatic backup download filename=%s error=%s", backup_filename, exc)
        add_flash_message(request, str(exc), "error")
        return RedirectResponse(url="/diagnostics#automatic-backups", status_code=303)

    record_audit_event(
        database_session,
        actor=actor,
        action="debug.automatic_backup.downloaded",
        request=request,
        details={
            "filename": backup_filename,
            "size_bytes": len(content),
        },
    )
    database_session.commit()
    logger.warning(
        "Downloaded automatic TicketPilot backup filename=%s size_bytes=%s actor=%s",
        backup_filename,
        len(content),
        actor,
    )
    return Response(
        content=content,
        media_type=BACKUP_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{backup_filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/autotask/test")
@legacy_router.post("/autotask/test", include_in_schema=False)
async def test_autotask_api(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Test mandatory Autotask API connectivity from the debug page."""

    try:
        actor = require_debug_access(request, database_session)
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

    return RedirectResponse(url="/diagnostics", status_code=303)


@router.post("/sessions/logout-web-users")
@legacy_router.post("/sessions/logout-web-users", include_in_schema=False)
async def logout_all_web_users(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Force every managed web user to authenticate again."""

    try:
        actor = require_debug_access(request, database_session)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))

    result = invalidate_all_web_user_sessions(database_session)
    record_audit_event(
        database_session,
        actor=actor,
        action="debug.web_user_sessions.invalidated",
        request=request,
        details={
            "affected_user_count": result.affected_user_count,
            "invalidated_at_utc": result.invalidated_at_utc.isoformat(),
        },
    )
    database_session.commit()
    add_flash_message(
        request,
        f"Signed out {result.affected_user_count} web users. They must sign in again.",
        "success",
    )
    return RedirectResponse(url="/diagnostics#session-controls", status_code=303)
