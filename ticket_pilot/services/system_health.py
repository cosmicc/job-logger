"""Cached application health state used by Diagnostics and shared headers."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_pilot.config import Settings, settings
from ticket_pilot.models import CloudflareIPBlock, LoginFailureCounter
from ticket_pilot.services.database_diagnostics import DebugDatabaseSnapshot, collect_database_diagnostics_snapshot

MEBIBYTE_BYTES = 1024 * 1024
APP_HEALTH_SUMMARY_LIMIT = 240
APP_HEALTH_SEVERITY_RANK = {"ok": 0, "warning": 1, "critical": 2}

logger = logging.getLogger(__name__)


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
    available: bool = True


@dataclass(frozen=True)
class DebugDiskUsageSnapshot:
    """Disk usage summary rendered on the diagnostics page."""

    severity: str
    status_label: str
    volumes: tuple[DebugDiskUsageVolume, ...]
    warning_free_display: str = ""
    critical_free_display: str = ""


@dataclass(frozen=True)
class CachedAutotaskHealth:
    """In-process Autotask health state derived from recent provider activity."""

    available: bool
    summary: str
    operation: str | None
    checked_at_utc: datetime
    active_failure_count: int = 0
    active_operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppHealthIssue:
    """One visible reason the application needs administrator attention."""

    code: str
    label: str
    severity: str
    summary: str


@dataclass(frozen=True)
class AppHealthSnapshot:
    """Current app health summary for shared alerts and Diagnostics."""

    issues: tuple[AppHealthIssue, ...]

    @property
    def degraded(self) -> bool:
        """Return whether any monitored dependency currently needs attention."""

        return bool(self.issues)

    @property
    def severity(self) -> str:
        """Return the worst severity across active health issues."""

        if not self.issues:
            return "ok"
        return max(self.issues, key=lambda issue: APP_HEALTH_SEVERITY_RANK.get(issue.severity, 0)).severity

    @property
    def status_label(self) -> str:
        """Return the compact status label for Diagnostics banners."""

        if not self.issues:
            return "All monitored checks OK"
        if self.severity == "critical":
            return "App health critical"
        return "App health degraded"

    @property
    def alert_label(self) -> str:
        """Return concise button text for screen readers and hover titles."""

        if not self.issues:
            return "Application health is OK"
        if len(self.issues) == 1:
            return f"Application needs attention: {self.issues[0].label}"
        labels = ", ".join(issue.label for issue in self.issues)
        return f"Application needs attention: {labels}"


_AUTOTASK_HEALTH_LOCK = RLock()
_DISK_HEALTH_LOG_LOCK = RLock()
_unavailable_disk_paths: set[str] = set()
_cached_autotask_success_health = CachedAutotaskHealth(
    available=True,
    summary="No Autotask API failure has been recorded.",
    operation=None,
    checked_at_utc=datetime.now(UTC),
)
_cached_autotask_failures: dict[str, CachedAutotaskHealth] = {}


def _normalize_autotask_operation(operation: str | None) -> str:
    """Return the semantic Autotask operation label used for health tracking."""

    safe_operation = " ".join(str(operation or "Autotask API request").split())
    return safe_operation or "Autotask API request"


def _autotask_operation_key(operation: str | None) -> str:
    """Return the stable key for one semantic Autotask operation type."""

    return _normalize_autotask_operation(operation).casefold()


def _autotask_health_from_active_failures() -> CachedAutotaskHealth:
    """Return the public Autotask health snapshot from active operation failures."""

    if not _cached_autotask_failures:
        return _cached_autotask_success_health

    latest_failure = max(
        _cached_autotask_failures.values(),
        key=lambda health: health.checked_at_utc,
    )
    active_operations = tuple(
        sorted(
            operation
            for operation in (
                health.operation
                for health in _cached_autotask_failures.values()
            )
            if operation
        )
    )
    return CachedAutotaskHealth(
        available=False,
        summary=latest_failure.summary,
        operation=latest_failure.operation,
        checked_at_utc=latest_failure.checked_at_utc,
        active_failure_count=len(_cached_autotask_failures),
        active_operations=active_operations,
    )


def _format_file_size(size_bytes: int) -> str:
    """Return a compact human-readable file size."""

    units = ("B", "KB", "MB", "GB", "TB")
    size_value = float(size_bytes)
    for unit in units:
        if size_value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size_value)} B"
            return f"{size_value:.1f} {unit}"
        size_value /= 1024

    return f"{size_bytes} B"


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


def _record_disk_probe_unavailable(label: str, configured_path: str) -> None:
    """Log the first failed probe for a path without exposing raw OS details."""

    with _DISK_HEALTH_LOG_LOCK:
        if configured_path in _unavailable_disk_paths:
            return
        _unavailable_disk_paths.add(configured_path)

    logger.warning(
        "Monitored storage is unavailable label=%s path=%s; application requests will continue",
        label,
        configured_path,
    )


def _record_disk_probe_available(label: str, configured_path: str) -> None:
    """Log recovery once after a monitored path becomes readable again."""

    with _DISK_HEALTH_LOG_LOCK:
        if configured_path not in _unavailable_disk_paths:
            return
        _unavailable_disk_paths.remove(configured_path)

    logger.info(
        "Monitored storage recovered label=%s path=%s",
        label,
        configured_path,
    )


def _unavailable_disk_usage_volume(label: str, configured_path: str) -> DebugDiskUsageVolume:
    """Return display-safe critical metadata for an unreadable storage path."""

    return DebugDiskUsageVolume(
        label=label,
        configured_path=configured_path,
        measured_path=configured_path,
        total_display="Unavailable",
        used_display="Unavailable",
        free_display="Unavailable",
        used_percent=0.0,
        used_percent_display="Unavailable",
        severity="critical",
        status_label="Unavailable",
        configured_paths=(f"{label}: {configured_path}",),
        measured_paths=(configured_path,),
        available=False,
    )


def _disk_usage_severity(
    free_bytes: int,
    *,
    application_settings: Settings = settings,
) -> tuple[str, str]:
    """Return free-space-only diagnostic severity for a filesystem."""

    critical_free_bytes = application_settings.app_health_disk_critical_free_mb * MEBIBYTE_BYTES
    warning_free_bytes = application_settings.app_health_disk_warning_free_mb * MEBIBYTE_BYTES
    if free_bytes < critical_free_bytes:
        return "critical", "Critical"
    if free_bytes < warning_free_bytes:
        return "warning", "Nearing full"
    return "ok", "OK"


def _serialize_disk_usage_volume(label: str, configured_path: str) -> DebugDiskUsageVolume:
    """Return disk usage metadata for one configured diagnostics path."""

    try:
        measured_path = _existing_disk_probe_path(configured_path)
        usage = shutil.disk_usage(measured_path)
    except OSError:
        # Storage health is observational. A stale NFS handle or temporarily
        # unreadable mount must raise an alert without breaking app workflows.
        _record_disk_probe_unavailable(label, configured_path)
        return _unavailable_disk_usage_volume(label, configured_path)

    _record_disk_probe_available(label, configured_path)
    used_percent = 0.0
    if usage.total > 0:
        used_percent = (usage.used / usage.total) * 100
    severity, status_label = _disk_usage_severity(usage.free)

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
        available=True,
    )


def _combine_disk_usage_volumes(volumes: tuple[DebugDiskUsageVolume, ...]) -> tuple[DebugDiskUsageVolume, ...]:
    """Combine monitored paths that report identical used and total storage."""

    combined_volumes: list[DebugDiskUsageVolume] = []
    volume_indexes_by_usage: dict[tuple[int | str, int | str], int] = {}

    for volume in volumes:
        if not volume.available:
            # Separate inaccessible mounts so Diagnostics keeps the failing
            # configured path explicit instead of merging generic values.
            usage_key = ("unavailable", volume.configured_path)
        else:
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
            available=existing_volume.available and volume.available,
        )

    return tuple(combined_volumes)


def collect_disk_usage_snapshot() -> DebugDiskUsageSnapshot:
    """Return the worst current disk state across key app-visible paths."""

    monitored_paths = (
        ("App filesystem", "/"),
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
    if any(not volume.available for volume in combined_volumes):
        status_label = "Storage unavailable"
    elif worst_volume.severity == "warning":
        status_label = "Disk space nearing full"
    elif worst_volume.severity == "critical":
        status_label = "Disk space critical"

    return DebugDiskUsageSnapshot(
        severity=worst_volume.severity,
        status_label=status_label,
        volumes=combined_volumes,
        warning_free_display=_format_file_size(settings.app_health_disk_warning_free_mb * MEBIBYTE_BYTES),
        critical_free_display=_format_file_size(settings.app_health_disk_critical_free_mb * MEBIBYTE_BYTES),
    )


def _issue_summary(summary: str) -> str:
    """Return bounded single-line issue text safe for headers and notifications."""

    safe_summary = " ".join(str(summary or "").split())
    if len(safe_summary) > APP_HEALTH_SUMMARY_LIMIT:
        safe_summary = f"{safe_summary[: APP_HEALTH_SUMMARY_LIMIT - 1].rstrip()}..."
    return safe_summary


def record_autotask_api_failure(summary: str, *, operation: str | None = None) -> None:
    """Mark one Autotask operation as degraded until that operation succeeds."""

    safe_summary = _issue_summary(summary or "Autotask API access failed.")
    safe_operation = _normalize_autotask_operation(operation)
    with _AUTOTASK_HEALTH_LOCK:
        _cached_autotask_failures[_autotask_operation_key(safe_operation)] = CachedAutotaskHealth(
            available=False,
            summary=safe_summary,
            operation=safe_operation,
            checked_at_utc=datetime.now(UTC),
        )


def record_autotask_api_success(*, operation: str | None = None) -> None:
    """Clear the cached Autotask alert for the matching operation type only."""

    with _AUTOTASK_HEALTH_LOCK:
        global _cached_autotask_success_health
        if operation is None:
            _cached_autotask_failures.clear()
        else:
            _cached_autotask_failures.pop(_autotask_operation_key(operation), None)
        _cached_autotask_success_health = CachedAutotaskHealth(
            available=True,
            summary="Autotask API access succeeded.",
            operation=_normalize_autotask_operation(operation) if operation is not None else None,
            checked_at_utc=datetime.now(UTC),
        )


def record_autotask_connectivity_result(
    *,
    available: bool,
    summary: str,
    operation: str | None = None,
) -> None:
    """Store the result of an explicit Diagnostics connectivity check."""

    connectivity_operation = "Autotask connectivity check"
    if available:
        record_autotask_api_success(operation=connectivity_operation)
        return

    record_autotask_api_failure(summary, operation=connectivity_operation)


def cached_autotask_health() -> CachedAutotaskHealth:
    """Return the current in-process Autotask health state."""

    with _AUTOTASK_HEALTH_LOCK:
        return _autotask_health_from_active_failures()


def reset_cached_autotask_health() -> None:
    """Reset cached Autotask state for tests and fresh application starts."""

    record_autotask_api_success(operation=None)


def _disk_health_issue(disk_usage: DebugDiskUsageSnapshot) -> AppHealthIssue | None:
    """Return a disk issue when app-visible storage is low."""

    if disk_usage.severity != "ok":
        return AppHealthIssue(
            code="disk-space",
            label=disk_usage.status_label,
            severity=disk_usage.severity,
            summary=disk_usage.status_label,
        )
    return None


def _autotask_health_issue() -> AppHealthIssue | None:
    """Return the cached Autotask issue when any semantic operation is failing."""

    autotask_health = cached_autotask_health()
    if not autotask_health.available:
        return AppHealthIssue(
            code="autotask-api",
            label="Autotask API needs attention",
            severity="critical",
            summary=autotask_health.summary,
        )
    return None


def _database_status_issue(database_snapshot: DebugDatabaseSnapshot) -> AppHealthIssue | None:
    """Return a database availability issue when the probe cannot connect."""

    if database_snapshot.available:
        return None
    return AppHealthIssue(
        code="database-status",
        label="Database unavailable",
        severity="critical",
        summary="Database connectivity is unavailable.",
    )


def _database_latency_issue(database_snapshot: DebugDatabaseSnapshot) -> AppHealthIssue | None:
    """Return a database latency issue when the safe probe is too slow."""

    if not database_snapshot.available or database_snapshot.latency_ms is None:
        return None

    latency_ms = database_snapshot.latency_ms
    if latency_ms >= settings.app_health_db_latency_critical_ms:
        return AppHealthIssue(
            code="database-latency",
            label="Database latency critical",
            severity="critical",
            summary=f"Database query latency is {latency_ms:.1f} ms.",
        )
    if latency_ms >= settings.app_health_db_latency_warning_ms:
        return AppHealthIssue(
            code="database-latency",
            label="Database latency high",
            severity="warning",
            summary=f"Database query latency is {latency_ms:.1f} ms.",
        )
    return None


def _database_pool_issue(database_snapshot: DebugDatabaseSnapshot) -> AppHealthIssue | None:
    """Return a database connection-pool pressure issue when usage is high."""

    pool_pressure = database_snapshot.pool.pressure_percent
    if not database_snapshot.available or pool_pressure is None:
        return None

    checked_out = database_snapshot.pool.checked_out
    configured_limit = database_snapshot.pool.configured_limit
    summary = (
        f"Database connection-pool pressure is {pool_pressure:.1f}% "
        f"({checked_out} checked out of {configured_limit})."
    )
    if pool_pressure >= settings.app_health_db_pool_critical_percent:
        return AppHealthIssue(
            code="database-pool-pressure",
            label="Database pool pressure critical",
            severity="critical",
            summary=summary,
        )
    if pool_pressure >= settings.app_health_db_pool_warning_percent:
        return AppHealthIssue(
            code="database-pool-pressure",
            label="Database pool pressure high",
            severity="warning",
            summary=summary,
        )
    return None


def _login_protection_issue(database_session: Session | None, *, now_utc: datetime | None = None) -> AppHealthIssue | None:
    """Return an issue when login protection has active local lockouts or blocks."""

    if database_session is None:
        return None

    current_dt = now_utc or datetime.now(UTC)
    lockout_cutoff = current_dt - timedelta(minutes=settings.login_local_lockout_minutes)
    active_lockout_count = database_session.scalar(
        select(func.count(LoginFailureCounter.id)).where(
            LoginFailureCounter.failed_count >= settings.cloudflare_auto_block_failed_login_attempts,
            LoginFailureCounter.last_failed_at_utc.is_not(None),
            LoginFailureCounter.last_failed_at_utc >= lockout_cutoff,
        )
    ) or 0
    app_managed_block_count = database_session.scalar(select(func.count(CloudflareIPBlock.id))) or 0

    if active_lockout_count <= 0 and app_managed_block_count <= 0:
        return None

    parts: list[str] = []
    if active_lockout_count:
        parts.append(f"{active_lockout_count} active local login lockout{'s' if active_lockout_count != 1 else ''}")
    if app_managed_block_count:
        parts.append(f"{app_managed_block_count} app-managed Cloudflare IP block{'s' if app_managed_block_count != 1 else ''}")

    return AppHealthIssue(
        code="login-protection",
        label="Login protection active",
        severity="warning",
        summary=f"Login protection is active: {', '.join(parts)}.",
    )


def collect_app_health_snapshot(
    *,
    database_session: Session | None = None,
    disk_usage: DebugDiskUsageSnapshot | None = None,
    database_snapshot: DebugDatabaseSnapshot | None = None,
) -> AppHealthSnapshot:
    """Return degraded app state without live external provider probes."""

    issues: list[AppHealthIssue] = []
    disk_issue = _disk_health_issue(disk_usage or collect_disk_usage_snapshot())
    if disk_issue is not None:
        issues.append(disk_issue)

    autotask_issue = _autotask_health_issue()
    if autotask_issue is not None:
        issues.append(autotask_issue)

    resolved_database_snapshot = database_snapshot or collect_database_diagnostics_snapshot()
    for issue in (
        _database_status_issue(resolved_database_snapshot),
        _database_latency_issue(resolved_database_snapshot),
        _database_pool_issue(resolved_database_snapshot),
    ):
        if issue is not None:
            issues.append(issue)
    if resolved_database_snapshot.available:
        login_issue = _login_protection_issue(database_session)
        if login_issue is not None:
            issues.append(login_issue)

    return AppHealthSnapshot(issues=tuple(issues))
