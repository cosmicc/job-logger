"""Cached application health state used by Diagnostics and shared headers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from job_logger.config import settings

DISK_SPACE_WARNING_USED_PERCENT = 85.0
DISK_SPACE_CRITICAL_USED_PERCENT = 95.0
DISK_SPACE_WARNING_FREE_BYTES = 5 * 1024 * 1024 * 1024
DISK_SPACE_CRITICAL_FREE_BYTES = 1 * 1024 * 1024 * 1024
APP_HEALTH_SUMMARY_LIMIT = 240


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
    """Disk usage summary rendered on the diagnostics page."""

    severity: str
    status_label: str
    volumes: tuple[DebugDiskUsageVolume, ...]


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
    """Current app health summary for admin-only top-bar alerts."""

    issues: tuple[AppHealthIssue, ...]

    @property
    def degraded(self) -> bool:
        """Return whether any monitored dependency currently needs attention."""

        return bool(self.issues)

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


def collect_disk_usage_snapshot() -> DebugDiskUsageSnapshot:
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


def record_autotask_api_failure(summary: str, *, operation: str | None = None) -> None:
    """Mark one Autotask operation as degraded until that operation succeeds."""

    safe_summary = " ".join(str(summary or "Autotask API access failed.").split())
    if len(safe_summary) > APP_HEALTH_SUMMARY_LIMIT:
        safe_summary = f"{safe_summary[: APP_HEALTH_SUMMARY_LIMIT - 1].rstrip()}..."
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


def collect_app_health_snapshot() -> AppHealthSnapshot:
    """Return admin-visible degraded app state without live external probes."""

    issues: list[AppHealthIssue] = []
    disk_usage = collect_disk_usage_snapshot()
    if disk_usage.severity != "ok":
        issues.append(
            AppHealthIssue(
                code="disk-space",
                label=disk_usage.status_label,
                severity=disk_usage.severity,
                summary=disk_usage.status_label,
            )
        )

    autotask_health = cached_autotask_health()
    if not autotask_health.available:
        issues.append(
            AppHealthIssue(
                code="autotask-api",
                label="Autotask API needs attention",
                severity="critical",
                summary=autotask_health.summary,
            )
        )

    return AppHealthSnapshot(issues=tuple(issues))
