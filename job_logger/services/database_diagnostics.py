"""Display-safe database diagnostics for the admin Diagnostics page."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from job_logger import database
from job_logger.config import settings


@dataclass(frozen=True)
class DebugDatabasePoolSnapshot:
    """Connection-pool statistics that do not expose endpoint details."""

    class_name: str
    size_display: str
    checked_in_display: str
    checked_out_display: str
    overflow_display: str
    configured_limit_display: str
    timeout_display: str
    recycle_display: str


@dataclass(frozen=True)
class DebugDatabaseSnapshot:
    """Database status rendered on the Diagnostics page."""

    available: bool
    status_label: str
    latency_display: str
    backend_display: str
    driver_display: str
    migration_revision: str
    pool: DebugDatabasePoolSnapshot

    @property
    def severity(self) -> str:
        """Return the CSS severity token for this database state."""

        return "ok" if self.available else "critical"


def _pool_metric_display(pool: object, method_name: str) -> str:
    """Return one SQLAlchemy pool metric when the pool implementation has it."""

    metric_method = getattr(pool, method_name, None)
    if not callable(metric_method):
        return "n/a"

    try:
        return str(metric_method())
    except Exception:
        return "n/a"


def _configured_limit_display() -> str:
    """Return configured non-SQLite pool capacity without exposing endpoint data."""

    if database.engine.dialect.name == "sqlite":
        return "n/a"
    return str(settings.database_pool_size + settings.database_max_overflow)


def _pool_snapshot() -> DebugDatabasePoolSnapshot:
    """Return display-safe SQLAlchemy pool data."""

    pool = database.engine.pool
    timeout_display = "n/a"
    recycle_display = "n/a"
    if database.engine.dialect.name != "sqlite":
        timeout_display = f"{settings.database_pool_timeout_seconds:.1f}s"
        recycle_display = f"{settings.database_pool_recycle_seconds}s"

    return DebugDatabasePoolSnapshot(
        class_name=pool.__class__.__name__,
        size_display=_pool_metric_display(pool, "size"),
        checked_in_display=_pool_metric_display(pool, "checkedin"),
        checked_out_display=_pool_metric_display(pool, "checkedout"),
        overflow_display=_pool_metric_display(pool, "overflow"),
        configured_limit_display=_configured_limit_display(),
        timeout_display=timeout_display,
        recycle_display=recycle_display,
    )


def _migration_revision() -> str:
    """Return the current Alembic revision when the version table exists."""

    try:
        with database.engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        return "Not recorded"

    safe_revision = str(revision or "").strip()
    return safe_revision or "Not recorded"


def collect_database_diagnostics_snapshot() -> DebugDatabaseSnapshot:
    """Return current database status without exposing URLs, hosts, or secrets."""

    backend_display = database.engine.dialect.name
    driver_display = database.engine.dialect.driver
    pool_snapshot = _pool_snapshot()
    start_time = perf_counter()
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar()
    except SQLAlchemyError:
        return DebugDatabaseSnapshot(
            available=False,
            status_label="Needs attention",
            latency_display="Unavailable",
            backend_display=backend_display,
            driver_display=driver_display,
            migration_revision="Unavailable",
            pool=pool_snapshot,
        )

    latency_ms = (perf_counter() - start_time) * 1000
    return DebugDatabaseSnapshot(
        available=True,
        status_label="Connected",
        latency_display=f"{latency_ms:.1f} ms",
        backend_display=backend_display,
        driver_display=driver_display,
        migration_revision=_migration_revision(),
        pool=pool_snapshot,
    )
