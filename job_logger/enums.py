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
    FOLLOW_UP = "follow_up"
    COMPLETE = "complete"


class WorkLocation(StrEnum):
    """Where the work was performed for Autotask time-entry notes."""

    REMOTE = "remote"
    ON_SITE = "on_site"


class ThemeMode(StrEnum):
    """Supported per-user visual themes."""

    DARK = "dark"
    LIGHT = "light"


class TranscriptionStatus(StrEnum):
    """State of the most recent speech-to-text attempt for a job."""

    NOT_REQUESTED = "not_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
