"""Application enum values stored in PostgreSQL as readable strings."""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Workflow state for a locally recorded work job."""

    ACTIVE = "active"
    READY_FOR_REVIEW = "ready_for_review"
    SUBMITTED = "submitted"
    SUBMISSION_FAILED = "submission_failed"
    REJECTED = "rejected"


class TicketStatus(StrEnum):
    """Supported local ticket status choices requested for Autotask review."""

    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    WAITING_PARTS = "waiting_parts"
    MFG_TROUBLE_TICKET = "mfg_trouble_ticket"
    FOLLOW_UP = "follow_up"
    COMPLETE = "complete"


class EntryType(StrEnum):
    """Supported Autotask record types that a local job can submit.

    ``ticket_note`` is retained as the stored compatibility value, but it also
    represents a TaskNotes record when the work target is a project task.
    """

    TIME_ENTRY = "time_entry"
    TICKET_NOTE = "ticket_note"


class WorkTargetType(StrEnum):
    """Autotask entity that owns a job's time entry or note."""

    TICKET = "ticket"
    PROJECT_TASK = "project_task"


class WorkLocation(StrEnum):
    """Where the work was performed for Autotask time-entry notes."""

    REMOTE = "remote"
    ON_SITE = "on_site"


class ThemeMode(StrEnum):
    """Supported per-user background and surface profiles."""

    DARK = "dark"
    LIGHT = "light"
    LIGHT_SAGE = "light-sage"
    LIGHT_SKY = "light-sky"
    DARK_MIDNIGHT = "dark-midnight"
    DARK_GRAPHITE = "dark-graphite"
    DARK_FOREST = "dark-forest"
    DARK_PLUM = "dark-plum"


class HighlightColor(StrEnum):
    """Supported per-user highlight color families."""

    TEAL = "teal"
    SAGE = "sage"
    SKY = "sky"
    BLUE = "blue"
    INDIGO = "indigo"
    AMBER = "amber"
    ORANGE = "orange"
    MINT = "mint"
    LAVENDER = "lavender"
    ROSE = "rose"


class NavigationApp(StrEnum):
    """Supported per-user navigation launch targets."""

    NONE = "none"
    DEVICE_DEFAULT = "device_default"
    GOOGLE_MAPS = "google_maps"
    WAZE = "waze"
    APPLE_MAPS = "apple_maps"


class TranscriptionStatus(StrEnum):
    """State of the most recent speech-to-text attempt for a job."""

    NOT_REQUESTED = "not_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
