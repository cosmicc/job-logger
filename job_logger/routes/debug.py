"""Troubleshooting routes for Autotask and authentication diagnostics."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from job_logger.config import settings
from job_logger.database import get_database_session
from job_logger.logging_config import redact_sensitive_text
from job_logger.models import CloudflareIPBlock, HiddenLoginFailure, Job, SubmissionAttempt, WebUser
from job_logger.security import add_flash_message, require_super_admin, validate_csrf_token
from job_logger.services.audit import record_audit_event
from job_logger.services.autotask import AutotaskConnectivityResult, test_autotask_connectivity
from job_logger.services.backups import (
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
from job_logger.services.cloudflare_blocks import (
    CloudflareBlockError,
    cloudflare_block_for_ip,
    cloudflare_ip_blocking_configured,
    create_app_cloudflare_block,
    ip_is_allowlisted,
    normalize_ip_address,
    remove_app_cloudflare_block,
)
from job_logger.services.login_failures import read_login_failures_page, read_login_successes_page
from job_logger.services.session_control import invalidate_all_web_user_sessions
from job_logger.time_utils import format_local_display
from job_logger.ui import template_context, templates
from job_logger.version import APP_VERSION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/debug", tags=["debug"])
DIAGNOSTIC_TABLE_PAGE_SIZE = 10
LOGIN_ATTEMPT_PAGE_SIZE = DIAGNOSTIC_TABLE_PAGE_SIZE
CLOUDFLARE_BLOCK_PAGE_SIZE = DIAGNOSTIC_TABLE_PAGE_SIZE
SUBMISSION_ATTEMPT_PAGE_SIZE = DIAGNOSTIC_TABLE_PAGE_SIZE
APP_LOG_TAIL_LINES = 10
MAX_APP_LOG_LINE_CHARS = 2000
DISK_SPACE_WARNING_USED_PERCENT = 85.0
DISK_SPACE_CRITICAL_USED_PERCENT = 95.0
DISK_SPACE_WARNING_FREE_BYTES = 5 * 1024 * 1024 * 1024
DISK_SPACE_CRITICAL_FREE_BYTES = 1 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class DebugDiskUsageVolume:
    """Display-safe disk usage details for one monitored filesystem path."""

    label: str
    configured_path: str
    measured_path: str
    total_display: str
    used_display: str
    free_display: str
    used_percent: float
    used_percent_display: str
    severity: str
    status_label: str
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    configured_paths: tuple[str, ...] = ()
    measured_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DebugDiskUsageSnapshot:
    """Disk usage summary rendered on the super-admin diagnostics page."""

    severity: str
    status_label: str
    volumes: tuple[DebugDiskUsageVolume, ...]


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


def _format_file_size(size_bytes: int) -> str:
    """Return a compact human-readable file size for diagnostics."""

    units = ("B", "KB", "MB", "GB", "TB")
    size_value = float(size_bytes)
    for unit in units:
        if size_value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size_value)} B"
            return f"{size_value:.1f} {unit}"
        size_value /= 1024

    return f"{size_bytes} B"


def _short_automatic_backup_filename(filename: str) -> str:
    """Return a compact display label while preserving the full backup filename."""

    return filename.removeprefix(AUTOMATIC_BACKUP_FILENAME_PREFIX).removesuffix(AUTOMATIC_BACKUP_FILENAME_SUFFIX)


def _existing_disk_probe_path(configured_path: str) -> Path:
    """Return an existing path that can be passed to ``shutil.disk_usage``."""

    candidate = Path(configured_path or "/").expanduser()
    if not candidate.is_absolute():
        candidate = candidate.resolve(strict=False)

    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent

    if candidate.exists():
        return candidate

    return Path("/")


def _disk_usage_severity(used_percent: float, free_bytes: int) -> tuple[str, str]:
    """Return the diagnostic severity and display label for a filesystem."""

    if used_percent >= DISK_SPACE_CRITICAL_USED_PERCENT or free_bytes <= DISK_SPACE_CRITICAL_FREE_BYTES:
        return "critical", "Critical"
    if used_percent >= DISK_SPACE_WARNING_USED_PERCENT or free_bytes <= DISK_SPACE_WARNING_FREE_BYTES:
        return "warning", "Nearing full"
    return "ok", "OK"


def _serialize_disk_usage_volume(label: str, configured_path: str) -> DebugDiskUsageVolume:
    """Return disk usage metadata for one configured diagnostics path."""

    measured_path = _existing_disk_probe_path(configured_path)
    usage = shutil.disk_usage(measured_path)
    used_percent = 0.0
    if usage.total > 0:
        used_percent = (usage.used / usage.total) * 100
    severity, status_label = _disk_usage_severity(used_percent, usage.free)

    return DebugDiskUsageVolume(
        label=label,
        configured_path=configured_path,
        measured_path=str(measured_path),
        total_display=_format_file_size(usage.total),
        used_display=_format_file_size(usage.used),
        free_display=_format_file_size(usage.free),
        used_percent=round(used_percent, 1),
        used_percent_display=f"{used_percent:.1f}%",
        severity=severity,
        status_label=status_label,
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        configured_paths=(f"{label}: {configured_path}",),
        measured_paths=(str(measured_path),),
    )


def _combine_disk_usage_volumes(volumes: tuple[DebugDiskUsageVolume, ...]) -> tuple[DebugDiskUsageVolume, ...]:
    """Combine monitored paths that report identical used and total storage."""

    combined_volumes: list[DebugDiskUsageVolume] = []
    volume_indexes_by_usage: dict[tuple[int | str, int | str], int] = {}

    for volume in volumes:
        usage_key = (
            (volume.used_bytes, volume.total_bytes)
            if volume.total_bytes > 0
            else (volume.used_display, volume.total_display)
        )

        existing_index = volume_indexes_by_usage.get(usage_key)
        if existing_index is None:
            volume_indexes_by_usage[usage_key] = len(combined_volumes)
            combined_volumes.append(volume)
            continue

        existing_volume = combined_volumes[existing_index]
        labels = tuple(dict.fromkeys((*existing_volume.label.split(", "), volume.label)))
        configured_paths = tuple(
            dict.fromkeys(
                (
                    *(existing_volume.configured_paths or (existing_volume.configured_path,)),
                    *(volume.configured_paths or (volume.configured_path,)),
                )
            )
        )
        measured_paths = tuple(
            dict.fromkeys(
                (
                    *(existing_volume.measured_paths or (existing_volume.measured_path,)),
                    *(volume.measured_paths or (volume.measured_path,)),
                )
            )
        )
        combined_volumes[existing_index] = DebugDiskUsageVolume(
            label=", ".join(labels),
            configured_path=", ".join(configured_paths),
            measured_path=", ".join(measured_paths),
            total_display=existing_volume.total_display,
            used_display=existing_volume.used_display,
            free_display=existing_volume.free_display,
            used_percent=existing_volume.used_percent,
            used_percent_display=existing_volume.used_percent_display,
            severity=existing_volume.severity,
            status_label=existing_volume.status_label,
            total_bytes=existing_volume.total_bytes,
            used_bytes=existing_volume.used_bytes,
            free_bytes=existing_volume.free_bytes,
            configured_paths=configured_paths,
            measured_paths=measured_paths,
        )

    return tuple(combined_volumes)


def _collect_disk_usage_snapshot() -> DebugDiskUsageSnapshot:
    """Return the worst current disk state across key app-visible paths."""

    monitored_paths = (
        ("App filesystem", "/"),
        ("Log directory", settings.log_dir),
        ("Backup directory", settings.automatic_backup_dir),
    )
    volumes = tuple(
        _serialize_disk_usage_volume(label, configured_path)
        for label, configured_path in monitored_paths
    )
    combined_volumes = _combine_disk_usage_volumes(volumes)
    severity_rank = {"ok": 0, "warning": 1, "critical": 2}
    worst_volume = max(combined_volumes, key=lambda volume: severity_rank[volume.severity])
    status_label = "Disk space OK"
    if worst_volume.severity == "warning":
        status_label = "Disk space nearing full"
    elif worst_volume.severity == "critical":
        status_label = "Disk space critical"

    return DebugDiskUsageSnapshot(
        severity=worst_volume.severity,
        status_label=status_label,
        volumes=combined_volumes,
    )


def _serialize_automatic_backup(backup_file: AutomaticBackupFile) -> DebugAutomaticBackup:
    """Return display-safe metadata for one automatic backup file."""

    return DebugAutomaticBackup(
        filename=backup_file.filename,
        display_filename=_short_automatic_backup_filename(backup_file.filename),
        created_at_display=format_local_display(backup_file.created_at_utc),
        size_display=_format_file_size(backup_file.size_bytes),
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


def _read_app_log_tail(log_dir: str, *, line_count: int = APP_LOG_TAIL_LINES) -> list[str]:
    """Return newest-first sanitized app log lines for the debug page."""

    app_log_path = Path(log_dir) / "app.log"
    if line_count <= 0 or not app_log_path.exists():
        return []

    recent_lines: deque[str] = deque(maxlen=line_count)
    try:
        with app_log_path.open("r", encoding="utf-8", errors="replace") as app_log_file:
            for raw_line in app_log_file:
                stripped_line = raw_line.rstrip("\n")
                if stripped_line:
                    recent_lines.append(stripped_line)
    except OSError as exc:
        logger.warning("Failed to read app log tail at %s: %s", app_log_path, exc)
        return []

    return [
        redact_sensitive_text(log_line)[:MAX_APP_LOG_LINE_CHARS]
        for log_line in reversed(recent_lines)
    ]


def _redirect_anonymous_or_raise(exc: HTTPException) -> RedirectResponse:
    """Redirect anonymous users to login while preserving super-admin-only 403s."""

    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)

    raise exc


def _debug_redirect(fragment: str) -> RedirectResponse:
    """Redirect back to one diagnostics section after a state-changing action."""

    return RedirectResponse(url=f"/debug#{fragment}", status_code=303)


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
        require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    submission_attempts_page = _paginate_submission_attempts(
        database_session,
        page=attempt_page,
        page_size=SUBMISSION_ATTEMPT_PAGE_SIZE,
    )
    hidden_login_failure_ids = set(database_session.scalars(select(HiddenLoginFailure.entry_id)))
    login_failures = read_login_failures_page(
        page=failure_page,
        page_size=LOGIN_ATTEMPT_PAGE_SIZE,
        hidden_entry_ids=hidden_login_failure_ids,
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
        normalized_ip = normalize_ip_address(failure.client_ip)
        login_failure_ip_statuses[failure.entry_id] = {
            "ip_address": normalized_ip or failure.client_ip,
            "valid": normalized_ip is not None,
            "blocked": normalized_ip in blocked_ip_addresses if normalized_ip else False,
            "allowlisted": ip_is_allowlisted(normalized_ip) if normalized_ip else False,
        }

    return templates.TemplateResponse(
        request,
        "debug.html",
        template_context(
            request,
            database_session=database_session,
            app_version=APP_VERSION,
            autotask_settings=_safe_autotask_config(),
            autotask_connectivity=request.session.get("autotask_connectivity_result"),
            login_success_log_path=settings.login_success_log_path,
            login_failure_log_path=settings.login_failure_log_path,
            login_failure_debug_rows=settings.login_failure_debug_rows,
            login_attempt_page_size=LOGIN_ATTEMPT_PAGE_SIZE,
            login_successes=read_login_successes_page(page=success_page, page_size=LOGIN_ATTEMPT_PAGE_SIZE),
            login_failures=login_failures,
            login_failure_ip_statuses=login_failure_ip_statuses,
            cloudflare_ip_blocks=cloudflare_ip_blocks_page.records,
            cloudflare_ip_blocks_page=cloudflare_ip_blocks_page,
            cloudflare_ip_blocking_configured=cloudflare_ip_blocking_configured(),
            disk_usage=_collect_disk_usage_snapshot(),
            submission_attempts=submission_attempts_page.records,
            submission_attempts_page=submission_attempts_page,
            submission_attempt_page_size=SUBMISSION_ATTEMPT_PAGE_SIZE,
            automatic_backups=[
                _serialize_automatic_backup(backup_file)
                for backup_file in list_automatic_backup_files(settings.automatic_backup_dir)
            ],
            automatic_backups_enabled=settings.automatic_backups_enabled,
            automatic_backup_dir=settings.automatic_backup_dir,
            backup_upload_max_mb=_backup_upload_max_mb(),
            app_log_path=str(Path(settings.log_dir) / "app.log"),
            app_log_lines=_read_app_log_tail(settings.log_dir),
            app_log_tail_lines=APP_LOG_TAIL_LINES,
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


@router.get("/logs/login-successes")
def download_login_success_log(request: Request) -> Response:
    """Download the raw successful-login JSONL log for authenticated diagnostics."""

    try:
        require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    log_path = Path(settings.login_success_log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Login success log not found")

    return Response(
        content=redact_sensitive_text(log_path.read_text(encoding="utf-8", errors="replace")),
        media_type="application/jsonl; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="job-logger-login-successes.log"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/login-failures/hide")
async def hide_login_failure_entry(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Hide one failed-login row from Diagnostics without editing the raw log."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    cleaned_entry_id = str(form_data.get("entry_id", "")).strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", cleaned_entry_id):
        raise HTTPException(status_code=400, detail="Invalid failed-login entry ID.")

    existing = database_session.scalar(
        select(HiddenLoginFailure)
        .where(HiddenLoginFailure.entry_id == cleaned_entry_id)
        .limit(1)
    )
    if existing is None:
        hidden_entry = HiddenLoginFailure(
            entry_id=cleaned_entry_id,
            client_ip=str(form_data.get("client_ip", "")).strip()[:64],
            occurred_at_utc=str(form_data.get("created_at_utc", "")).strip()[:40],
        )
        database_session.add(hidden_entry)
        record_audit_event(
            database_session,
            actor=actor,
            action="debug.login_failure.hidden",
            request=request,
            details={
                "entry_id": cleaned_entry_id,
                "client_ip": hidden_entry.client_ip,
            },
        )
        database_session.commit()
        add_flash_message(request, "Failed-login row hidden from Diagnostics.", "success")
    else:
        add_flash_message(request, "Failed-login row is already hidden.", "info")
    return _debug_redirect("login-failures")


@router.post("/cloudflare-blocks/block")
async def block_login_ip_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Create an app-managed Cloudflare block for a failed-login IP."""

    try:
        actor = require_super_admin(request)
    except HTTPException as exc:
        return _redirect_anonymous_or_raise(exc)

    form_data = await request.form()
    validate_csrf_token(request, str(form_data.get("csrf_token", "")))
    ip_address = str(form_data.get("ip_address", "")).strip()
    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip is None:
        add_flash_message(request, "Cannot block an invalid IP address.", "error")
        return _debug_redirect("login-failures")

    existing_block = cloudflare_block_for_ip(database_session, normalized_ip)
    if existing_block is not None:
        add_flash_message(request, "Cloudflare IP block is already active.", "info")
        return _debug_redirect("login-failures")

    try:
        block = create_app_cloudflare_block(
            database_session,
            normalized_ip,
            source="manual",
            reason="Diagnostics failed-login row block button",
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
            },
        )
        database_session.commit()
    except CloudflareBlockError as exc:
        database_session.rollback()
        add_flash_message(request, str(exc), "error")
        return _debug_redirect("login-failures")

    add_flash_message(request, "Cloudflare IP block is active.", "success")
    return _debug_redirect("login-failures")


@router.post("/cloudflare-blocks/unblock")
async def unblock_login_ip_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Remove one app-managed Cloudflare block and its local block-list row."""

    try:
        actor = require_super_admin(request)
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


@router.post("/automatic-backups/download")
async def download_automatic_backup_form(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> Response:
    """Download one retained automatic backup after strict filename validation."""

    try:
        actor = require_super_admin(request)
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
        return RedirectResponse(url="/debug#automatic-backups", status_code=303)

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
        "Downloaded automatic Job Logger backup filename=%s size_bytes=%s actor=%s",
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


@router.post("/sessions/logout-web-users")
async def logout_all_web_users(
    request: Request,
    database_session: Session = Depends(get_database_session),
) -> RedirectResponse:
    """Force every managed web user to authenticate again."""

    try:
        actor = require_super_admin(request)
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
    return RedirectResponse(url="/debug#session-controls", status_code=303)
