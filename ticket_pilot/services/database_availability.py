"""Database availability checks used by the temporary service page.

The web process must be able to start when PostgreSQL is temporarily offline so
operators and users see a controlled service-unavailable page instead of a
crashed container or an internal traceback. This module centralizes the safe
probe and the one-time migration retry that is needed when the Docker
entrypoint had to skip startup migrations.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from ticket_pilot import database
from ticket_pilot.config import Settings

logger = logging.getLogger(__name__)

DATABASE_STARTUP_MIGRATIONS_PENDING_ENV = "DATABASE_STARTUP_MIGRATIONS_PENDING"


def startup_migrations_are_pending() -> bool:
    """Return whether the entrypoint started the app before migrations ran."""

    return os.getenv(DATABASE_STARTUP_MIGRATIONS_PENDING_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class DatabaseAvailabilityMonitor:
    """Track database reachability without probing PostgreSQL on every request."""

    def __init__(self, *, migrations_pending: bool = False) -> None:
        """Initialize the monitor with the entrypoint migration state."""

        self._lock = threading.RLock()
        self._last_checked_at = 0.0
        self._last_available: bool | None = None
        self._migrations_pending = migrations_pending

    def mark_unavailable(self) -> None:
        """Record a failed database operation so later requests show limp mode."""

        with self._lock:
            self._last_checked_at = time.monotonic()
            self._last_available = False

    def database_available(self, application_settings: Settings, *, force: bool = False) -> bool:
        """Return whether the database is usable for normal request handling."""

        with self._lock:
            now = time.monotonic()
            if (
                not force
                and self._last_available is not None
                and now - self._last_checked_at < application_settings.database_unavailable_check_interval_seconds
            ):
                return self._last_available

            try:
                self._probe_database()
                if self._migrations_pending:
                    self._run_pending_migrations(application_settings)
            except Exception:
                self._last_checked_at = time.monotonic()
                self._last_available = False
                logger.warning("Database unavailable; serving the temporary service page.")
                return False

            self._last_checked_at = time.monotonic()
            self._last_available = True
            return True

    @staticmethod
    def _probe_database() -> None:
        """Open a connection and run the cheapest portable readiness query."""

        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def _run_pending_migrations(self, application_settings: Settings) -> None:
        """Run Alembic after a database outage prevented entrypoint migrations."""

        alembic_config = Config("alembic.ini")
        database_url = database.normalize_database_url(application_settings.database_url)
        alembic_config.set_main_option("sqlalchemy.url", database_url)
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            command.upgrade(alembic_config, "head")
        finally:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url
        self._migrations_pending = False
        logger.info("Database migrations completed after temporary database unavailability.")
