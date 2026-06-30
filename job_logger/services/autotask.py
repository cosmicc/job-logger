"""Autotask submission providers for TimeEntries and TicketNotes."""

from __future__ import annotations

import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from threading import RLock
from typing import Any

import httpx

from job_logger.config import Settings, settings
from job_logger.enums import EntryType, TicketStatus, WorkLocation
from job_logger.models import Job
from job_logger.services.system_health import (
    record_autotask_api_failure,
    record_autotask_api_success,
    record_autotask_connectivity_result,
)
from job_logger.time_utils import ensure_utc, format_autotask_datetime, local_date_for, local_day_bounds_utc, now_utc, rounded_duration_minutes

MAX_COMPANY_MATCHES_FOR_TICKET_LOOKUP = 10
MAX_TICKET_LOOKUP_RESULTS = 25
MAX_OPEN_TICKET_QUERY_RECORDS = MAX_TICKET_LOOKUP_RESULTS
MAX_RESOURCE_LOOKUP_RESULTS = 25
MAX_RESOURCE_NAME_LENGTH = 160
MAX_SERVICE_DESK_ROLE_NAME_LENGTH = 200
MAX_SERVICE_CALL_LOOKUP_RESULTS = 25
MAX_SERVICE_CALL_NAME_LENGTH = 240
MAX_SERVICE_CALL_DETAIL_LENGTH = 2000
MAX_TICKET_NOTE_LOOKUP_RESULTS = 100
MAX_TICKET_NOTE_TITLE_LENGTH = 250
MAX_TICKET_NOTE_BODY_LENGTH = 12000
MAX_TICKET_NOTE_AUTHOR_LENGTH = 160
MAX_TICKET_TIME_ENTRY_LOOKUP_RESULTS = 100
MAX_TICKET_TIME_ENTRY_SUMMARY_LENGTH = 12000
MAX_AUTOTASK_IN_FILTER_VALUES = 500
CUSTOMER_VISIBLE_TICKET_NOTE_PUBLISH_VALUE = 1
DEFAULT_TICKET_NOTE_TYPE = 1

WORK_LOCATION_DISPLAY_LABELS = {
    WorkLocation.REMOTE: "Remote",
    WorkLocation.ON_SITE: "On-Site",
}
WORK_LOCATION_SUMMARY_PREFIXES = {
    WorkLocation.REMOTE: "Remote.",
    WorkLocation.ON_SITE: "On-Site.",
}

TICKET_STATUS_DISPLAY_LABELS = {
    TicketStatus.IN_PROGRESS: "In progress",
    TicketStatus.WAITING_CUSTOMER: "Waiting customer",
    TicketStatus.WAITING_PARTS: "Waiting parts",
    TicketStatus.FOLLOW_UP: "Follow up",
    TicketStatus.COMPLETE: "Complete",
}
MIN_COMPANY_SEARCH_CHARACTERS = 3
MIN_RESOURCE_SEARCH_CHARACTERS = 2
REMOTE_SERVICE_CALL_PATTERN = re.compile(r"\bremote\b", re.IGNORECASE)
ON_SITE_SERVICE_CALL_PATTERN = re.compile(r"\bon[\s-]?site\b", re.IGNORECASE)
REMOTE_TICKET_SOURCE_LABELS = {"rmm alert", "datto alert", "bcdr alert", "email alert"}
RESOURCE_MATCH_TEXT_PATTERN = re.compile(r"[^a-z0-9]+")
SUMMARY_WORK_LOCATION_PREFIX_PATTERN = re.compile(
    r"^\s*(?P<prefix>on[\s-]?site|remote)\b(?:\s*[.:\-]\s*|\s+|$)(?P<summary>.*)\Z",
    re.IGNORECASE | re.DOTALL,
)

# AUTOTASK_CACHE_TTL_SECONDS is the default short TTL for status metadata and non-company lookups.
AUTOTASK_CACHE_TTL_SECONDS = 15 * 60

# COMPANY_CACHE_TTL_SECONDS is longer because company names are low-churn reference data.
COMPANY_CACHE_TTL_SECONDS = 2 * 60 * 60

# OPEN_TICKET_SELECTION_CACHE_TTL_SECONDS keeps the open-ticket list that the
# server just returned to the browser long enough for a click selection to reuse
# it. This avoids a second live Autotask Tickets query on the critical tap path
# while still expiring quickly so stale ticket state is not treated as durable.
OPEN_TICKET_SELECTION_CACHE_TTL_SECONDS = 2 * 60

# SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS keeps a selected-day service-call
# list long enough for a tap-to-start action to reuse server-resolved data.
SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS = 2 * 60

# AUTOTASK_MAX_RECORDS_PER_PAGE uses Autotask's maximum documented query page size.
AUTOTASK_MAX_RECORDS_PER_PAGE = 500

# AUTOTASK_MAX_PAGINATED_PAGES prevents runaway next-page loops from bad remote responses.
AUTOTASK_MAX_PAGINATED_PAGES = 100

# AUTOTASK_SAFE_ERROR_TEXT_LIMIT bounds remote error excerpts kept in UI/audit
# summaries so diagnostics stay actionable without storing full remote payloads.
AUTOTASK_SAFE_ERROR_TEXT_LIMIT = 240


@dataclass(frozen=True)
class _AutotaskCacheEntry:
    """In-process cache entry for non-secret Autotask lookup data."""

    # expires_at_monotonic is based on time.monotonic so wall-clock changes do not extend cache life.
    expires_at_monotonic: float

    # value stores only non-secret company metadata or ticket status labels.
    value: Any


# _AUTOTASK_CACHE_LOCK protects cache reads/writes across concurrent web requests.
_AUTOTASK_CACHE_LOCK = RLock()

# _COMPANY_SEARCH_CACHE stores raw active company records keyed by tenant URL and normalized query text.
_COMPANY_SEARCH_CACHE: dict[tuple[str, str], _AutotaskCacheEntry] = {}

# _COMPANY_ID_CACHE stores one selected company record keyed by tenant URL and Autotask company ID.
_COMPANY_ID_CACHE: dict[tuple[str, int], _AutotaskCacheEntry] = {}

# _RESOURCE_SEARCH_CACHE stores resource lookup options keyed by tenant URL and normalized name text.
_RESOURCE_SEARCH_CACHE: dict[tuple[str, str], _AutotaskCacheEntry] = {}

# _TICKET_STATUS_CACHE stores ticket status picklist labels keyed by tenant URL.
_TICKET_STATUS_CACHE: dict[str, _AutotaskCacheEntry] = {}

# _TICKET_SOURCE_CACHE stores ticket source picklist labels keyed by tenant URL.
_TICKET_SOURCE_CACHE: dict[str, _AutotaskCacheEntry] = {}

# _OPEN_TICKET_SELECTION_CACHE stores recently displayed open-ticket options
# keyed by tenant URL, selected client text, and selected Autotask company ID.
_OPEN_TICKET_SELECTION_CACHE: dict[tuple[str, str, int | None], _AutotaskCacheEntry] = {}

# _SERVICE_CALL_SELECTION_CACHE stores today's rendered service-call options
# keyed by tenant URL, resource, and local-day UTC bounds. It contains only
# non-secret ticket and company metadata already safe for the authenticated UI.
_SERVICE_CALL_SELECTION_CACHE: dict[tuple[str, int, str, str], _AutotaskCacheEntry] = {}

def _get_cached_value(cache_store: dict[Any, _AutotaskCacheEntry], cache_key: Any) -> Any | None:
    """Return a defensive copy of a cached value when its 15-minute TTL is valid."""

    current_monotonic_time = time.monotonic()
    with _AUTOTASK_CACHE_LOCK:
        cache_entry = cache_store.get(cache_key)
        if cache_entry is None:
            return None

        if cache_entry.expires_at_monotonic <= current_monotonic_time:
            cache_store.pop(cache_key, None)
            return None

        return deepcopy(cache_entry.value)


def _set_cached_value(
    cache_store: dict[Any, _AutotaskCacheEntry],
    cache_key: Any,
    value: Any,
    ttl_seconds: int = AUTOTASK_CACHE_TTL_SECONDS,
) -> None:
    """Store a defensive copy of non-secret Autotask lookup data for a bounded TTL."""

    cache_entry = _AutotaskCacheEntry(
        expires_at_monotonic=time.monotonic() + ttl_seconds,
        value=deepcopy(value),
    )
    with _AUTOTASK_CACHE_LOCK:
        cache_store[cache_key] = cache_entry


@dataclass(frozen=True)
class AutotaskCompanyOption:
    """Safe company data returned to the browser for client selection."""

    # company_id is the Autotask company/account ID used for exact ticket lookup.
    company_id: int

    # company_name is the Autotask display name shown in autocomplete results.
    company_name: str


@dataclass(frozen=True)
class AutotaskResourceOption:
    """Safe resource data returned to the super-admin web-user manager."""

    # resource_id is the Autotask Resource ID stored on the managed web user.
    resource_id: int

    # resource_name is formatted for humans as "First Last" when available.
    resource_name: str

    # first_name is included so the browser can explain why a result matched.
    first_name: str | None = None

    # last_name is included so the browser can explain why a result matched.
    last_name: str | None = None

    # email is optional non-secret directory context returned by Autotask.
    email: str | None = None


@dataclass(frozen=True)
class AutotaskServiceDeskRoleOption:
    """Safe active service-desk role option for one Autotask Resource."""

    # role_id is the ResourceServiceDeskRoles.roleID value used by TimeEntries.
    role_id: int

    # name is the optional human-readable Autotask Roles.name for the role ID.
    name: str | None = None

    # label is display-only role context safe for the super-admin user manager.
    label: str = ""

    # is_default mirrors ResourceServiceDeskRoles.isDefault when Autotask returns it.
    is_default: bool = False


@dataclass(frozen=True)
class AutotaskConnectivityResult:
    """Safe diagnostic result for the mandatory Autotask API dependency."""

    # provider records which configured provider was tested.
    provider: str

    # available is true only when the provider is ready for the job workflow.
    available: bool

    # summary is a short user-facing result that must not contain secrets.
    summary: str

    # tips lists actionable, non-secret fixes for the operator.
    tips: tuple[str, ...] = ()

    # checked_operations records which dependency checks completed.
    checked_operations: tuple[str, ...] = ()

    # failed_operation identifies the first dependency operation that failed.
    # It is intentionally a short local label, not a remote response body.
    failed_operation: str | None = None


@dataclass(frozen=True)
class AutotaskSubmissionResult:
    """Result returned by Autotask submission providers."""

    # provider identifies mock or live submission mode.
    provider: str

    # succeeded controls the local job state transition.
    succeeded: bool

    # external_id stores the remote Autotask TimeEntries or TicketNotes ID when
    # available.
    external_id: str | None

    # safe_error stores user-reviewable failure detail without secrets.
    safe_error: str | None

    # request_snapshot is a sanitized non-secret view of what was attempted.
    request_snapshot: dict[str, Any]


@dataclass(frozen=True)
class AutotaskTicketOption:
    """Safe ticket data returned to review users for ticket selection."""

    # ticket_number is the human Autotask number used by the review form.
    ticket_number: str

    # title helps the reviewer choose the correct open ticket.
    title: str

    # description is bounded read-only ticket context shown after selection.
    description: str | None

    # status_label is the current Autotask ticket status label.
    status_label: str

    # company_name is included because client-name searches can match more than one company.
    company_name: str

    # detected_work_location is inferred from safe ticket title/description text
    # and then ticket source as a fallback; it is not an authorization source.
    detected_work_location: WorkLocation | None = None

    # work_location_label is the human label displayed on open-ticket choices.
    work_location_label: str = "Not specified"

    # status_id is the Autotask ticket status picklist value when returned.
    status_id: int | None = None


@dataclass(frozen=True)
class AutotaskTicketNote:
    """Safe Autotask ticket-note data returned to authenticated job owners."""

    # note_id is the Autotask TicketNotes.id value used only for UI selection.
    note_id: int

    # title is bounded because note titles are external customer/work data.
    title: str

    # description is bounded note body text shown only inside the authenticated overlay.
    description: str | None

    # created_by is bounded display-only author metadata resolved from Autotask IDs.
    created_by: str | None = None

    # created_at_utc and updated_at_utc are display metadata from Autotask.
    created_at_utc: datetime | None = None
    updated_at_utc: datetime | None = None

    # note_type and publish are safe display metadata when Autotask returns them.
    note_type: str | None = None
    publish: int | None = None


SYSTEM_TICKET_NOTE_CONTEXT_TYPES = frozenset({"workflow rule", "service desk notification"})


def _normalized_ticket_note_context_type(value: str | None) -> str:
    """Return a stable note-type key for display filtering decisions."""

    return " ".join(str(value or "").split()).casefold()


def is_displayable_ticket_note_context(ticket_note: AutotaskTicketNote) -> bool:
    """Return whether an Autotask note should be shown in ticket context overlays."""

    note_type = _normalized_ticket_note_context_type(ticket_note.note_type)
    note_title = _normalized_ticket_note_context_type(ticket_note.title)
    return note_type not in SYSTEM_TICKET_NOTE_CONTEXT_TYPES and note_title not in SYSTEM_TICKET_NOTE_CONTEXT_TYPES


def filter_displayable_ticket_notes(ticket_notes: list[AutotaskTicketNote]) -> list[AutotaskTicketNote]:
    """Remove system-generated Autotask notes from authenticated ticket context."""

    return [ticket_note for ticket_note in ticket_notes if is_displayable_ticket_note_context(ticket_note)]


@dataclass(frozen=True)
class AutotaskTicketTimeEntry:
    """Safe Autotask time-entry data returned to authenticated job owners."""

    # time_entry_id is the Autotask TimeEntries.id value used only for UI selection.
    time_entry_id: int

    # resource_name is bounded first-name-first technician metadata resolved from Autotask.
    resource_name: str

    # start_at_utc and end_at_utc are displayed in the application timezone.
    start_at_utc: datetime | None
    end_at_utc: datetime | None

    # hours_worked is quantized for display but still kept numeric until the route formats it.
    hours_worked: Decimal | None

    # summary_notes is bounded customer/work text shown only inside the authenticated overlay.
    summary_notes: str | None


@dataclass(frozen=True)
class _ServiceDeskRoleLookup:
    """Resolved service-desk role context for a resource."""

    # role_id is a TimeEntries.roleID candidate from ResourceServiceDeskRoles.
    role_id: int

    # source describes the non-secret lookup that supplied role_id.
    source: str


@dataclass(frozen=True)
class AutotaskTicketTimeEntryContext:
    """Ticket fields required to create a matching Autotask TimeEntries row."""

    # ticket_id is the Autotask Tickets.id used by TimeEntries.ticketID.
    ticket_id: int

    # role_id is the role used for TimeEntries.roleID after provider validation.
    role_id: int

    # role_id_source describes the non-secret lookup that supplied role_id.
    role_id_source: str

    # assigned_resource_id is Tickets.assignedResourceID when Autotask returns it.
    assigned_resource_id: int | None

    # billing_code_id is the ticket Work Type ID; Autotask inherits it on create
    # when the TimeEntries payload omits billingCodeID.
    billing_code_id: int | None


@dataclass(frozen=True)
class AutotaskServiceCallOption:
    """Safe service-call data returned to the mobile start-work panel."""

    # service_call_id identifies the Autotask ServiceCalls row for display and audit.
    service_call_id: int

    # service_call_ticket_id identifies the specific ServiceCallTickets row the user clicked.
    service_call_ticket_id: int

    # service_call_name is the bounded display label from the service-call details.
    service_call_name: str

    # service_call_details stores bounded read-only context used for keyword detection.
    service_call_details: str | None

    # detected_work_location is set from service-call details, falling back to
    # remote-only ticket source labels when details do not name a work mode.
    detected_work_location: WorkLocation | None

    # work_location_label is the user-facing result of the service-call details keyword scan.
    work_location_label: str

    # ticket_number is the Autotask ticket number that will be stored on the started job.
    ticket_number: str

    # ticket_title is the associated Autotask ticket title shown in the service-call list.
    ticket_title: str

    # ticket_description is bounded Autotask ticket context stored on the job after the click.
    ticket_description: str | None

    # ticket_status_label is the current Autotask ticket status label from the
    # server-verified ticket lookup.
    ticket_status_label: str

    # client_name is the selected Autotask company name stored on the new active job.
    client_name: str

    # autotask_company_id is the selected Autotask company/account ID stored on the new active job.
    autotask_company_id: int

    # start_datetime_utc and end_datetime_utc are safe scheduled times used for
    # sorting, concise card display, and audit context.
    start_datetime_utc: datetime | None
    end_datetime_utc: datetime | None


class AutotaskSubmissionError(RuntimeError):
    """Raised for configuration or remote Autotask failures."""


MOCK_COMPANY_OPTIONS = (
    AutotaskCompanyOption(company_id=1001, company_name="Acme Services"),
    AutotaskCompanyOption(company_id=1002, company_name="Acme Holdings"),
)


class BaseAutotaskProvider:
    """Interface implemented by all Autotask providers."""

    provider_name = "base"

    def submit_job(
        self,
        job: Job,
        *,
        resource_id: int,
        default_service_desk_role_id: int | None = None,
    ) -> AutotaskSubmissionResult:
        """Submit a reviewed job to an external destination."""

        raise NotImplementedError

    def update_time_entry(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Update an existing external time entry for a submitted job."""

        raise NotImplementedError

    def update_ticket_note(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Update an existing external ticket note for a submitted job."""

        raise NotImplementedError

    def delete_time_entry(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Delete an existing external time entry for a submitted job."""

        raise NotImplementedError

    def delete_ticket_note(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Delete an existing external ticket note for a submitted job."""

        raise NotImplementedError

    def test_connectivity(self) -> AutotaskConnectivityResult:
        """Return whether this provider is ready for the job workflow."""

        raise NotImplementedError

    def list_open_tickets_for_client(
        self,
        client_name: str,
        autotask_company_id: int | None = None,
        *,
        resource_id: int | None = None,
    ) -> list[AutotaskTicketOption]:
        """Return open ticket options for the supplied client name."""

        raise NotImplementedError

    def list_ticket_notes(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketNote]:
        """Return safe read-only notes for one selected Autotask ticket."""

        raise NotImplementedError

    def list_ticket_time_entries(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketTimeEntry]:
        """Return safe read-only time entries for one selected Autotask ticket."""

        raise NotImplementedError

    def search_companies(self, query_text: str, *, resource_id: int | None = None) -> list[AutotaskCompanyOption]:
        """Return matching Autotask companies for an autocomplete query."""

        raise NotImplementedError

    def get_company_by_id(self, company_id: int, *, resource_id: int | None = None) -> AutotaskCompanyOption | None:
        """Return one active Autotask company by its selected ID."""

        raise NotImplementedError

    def search_resources(self, query_text: str) -> list[AutotaskResourceOption]:
        """Return matching Autotask resources for managed-user setup."""

        raise NotImplementedError

    def list_resource_service_desk_roles(self, resource_id: int) -> list[AutotaskServiceDeskRoleOption]:
        """Return active service-desk roles for one Autotask resource."""

        raise NotImplementedError

    def list_todays_service_calls_for_resource(
        self,
        resource_id: int,
        current_time_utc: datetime | None = None,
        local_service_date: date | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return service calls for one resource on a selected local date."""

        raise NotImplementedError


def _job_duration_hours(job: Job) -> Decimal:
    """Return rounded duration as decimal hours for Autotask."""

    if job.rounded_end_utc is None:
        raise AutotaskSubmissionError("Job has no rounded end time.")

    minutes = rounded_duration_minutes(job.rounded_start_utc, job.rounded_end_utc)
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _coerce_work_location(work_location: WorkLocation | str | None) -> WorkLocation:
    """Return a supported work-location value, defaulting legacy blanks to Remote."""

    raw_work_location = work_location or WorkLocation.REMOTE
    if isinstance(raw_work_location, WorkLocation):
        return raw_work_location

    try:
        return WorkLocation(str(raw_work_location).strip().lower().replace("-", "_").replace(" ", "_"))
    except ValueError:
        return WorkLocation.REMOTE


def _work_location_for_job(job: Job) -> WorkLocation:
    """Return the stored work-location mode, defaulting old in-memory jobs to Remote."""

    return _coerce_work_location(getattr(job, "work_location", None))


def split_autotask_summary_notes(
    summary_notes: str | None,
    fallback_work_location: WorkLocation | str | None,
) -> tuple[WorkLocation, str]:
    """Split a visible Autotask notes value into work location and note body.

    Review shows the final Autotask `summaryNotes` string so the operator can
    correct the leading Remote. or On-Site. value before submission. Local storage
    still keeps that work mode structured in `work_location`, so this parser
    accepts the current period-suffixed prefix and older visible prefixes while
    returning clean reviewer notes.
    """

    raw_summary_notes = (summary_notes or "").strip()
    work_location = _coerce_work_location(fallback_work_location)
    prefix_match = SUMMARY_WORK_LOCATION_PREFIX_PATTERN.match(raw_summary_notes)
    if prefix_match is None:
        return work_location, raw_summary_notes

    normalized_prefix = prefix_match.group("prefix").strip().casefold()
    work_location = WorkLocation.REMOTE if normalized_prefix == "remote" else WorkLocation.ON_SITE

    return work_location, prefix_match.group("summary").strip()


def detect_work_location_from_service_call_details(service_call_details: str | None) -> WorkLocation | None:
    """Return Remote or On-Site when service-call or ticket text names one."""

    detail_text = service_call_details or ""
    remote_match = REMOTE_SERVICE_CALL_PATTERN.search(detail_text)
    on_site_match = ON_SITE_SERVICE_CALL_PATTERN.search(detail_text)
    if remote_match is None and on_site_match is None:
        return None
    if remote_match is None:
        return WorkLocation.ON_SITE
    if on_site_match is None:
        return WorkLocation.REMOTE
    return WorkLocation.ON_SITE if on_site_match.start() < remote_match.start() else WorkLocation.REMOTE


def detect_work_location_from_ticket_source(ticket_source_label: str | None) -> WorkLocation | None:
    """Return a remote work-location signal for source labels that always mean remote work."""

    if not ticket_source_label:
        return None

    normalized_source_label = " ".join(ticket_source_label.strip().casefold().split())
    if normalized_source_label in REMOTE_TICKET_SOURCE_LABELS:
        return WorkLocation.REMOTE

    return None


def detect_work_location_from_text_or_ticket_source(
    detection_text: str | None,
    ticket_source_label: str | None,
) -> WorkLocation | None:
    """Detect work location from text first, then from the ticket source fallback."""

    detected_work_location = detect_work_location_from_service_call_details(detection_text)
    if detected_work_location is not None:
        return detected_work_location

    return detect_work_location_from_ticket_source(ticket_source_label)


def work_location_label_for_detection(work_location: WorkLocation | None) -> str:
    """Return the picker label for a detected work location."""

    if work_location is None:
        return "Not specified"

    return WORK_LOCATION_DISPLAY_LABELS[work_location]


def _safe_service_call_text(raw_text: Any, fallback_text: str, max_length: int) -> str:
    """Return bounded Autotask display text for service-call and ticket data."""

    safe_text = str(raw_text or "").strip()
    if not safe_text:
        safe_text = fallback_text

    return safe_text[:max_length]


def _ticket_source_label(ticket_record: dict[str, Any], source_labels: dict[int, str]) -> str | None:
    """Return the display label for a ticket source field value."""

    raw_source = ticket_record.get("source")
    if raw_source is None:
        return None

    try:
        source_id = int(raw_source)
    except (TypeError, ValueError):
        source_label = str(raw_source).strip()
        return source_label or None

    source_label = source_labels.get(source_id)
    if source_label:
        return source_label

    return None


def _safe_optional_resource_text(raw_text: Any, max_length: int = MAX_RESOURCE_NAME_LENGTH) -> str | None:
    """Return bounded optional Autotask resource text."""

    safe_text = str(raw_text or "").strip()
    if not safe_text:
        return None

    return safe_text[:max_length]


def _safe_optional_ticket_note_text(raw_text: Any, max_length: int) -> str | None:
    """Return bounded optional ticket-note text from Autotask."""

    safe_text = str(raw_text or "").strip()
    if not safe_text:
        return None

    return safe_text[:max_length]


def _safe_optional_ticket_time_entry_text(raw_text: Any, max_length: int) -> str | None:
    """Return bounded optional time-entry text from Autotask."""

    safe_text = str(raw_text or "").strip()
    if not safe_text:
        return None

    return safe_text[:max_length]


def _coerce_time_entry_hours(raw_hours: Any) -> Decimal | None:
    """Return non-negative Autotask time-entry hours rounded for display."""

    if raw_hours in (None, ""):
        return None

    try:
        hours_worked = Decimal(str(raw_hours))
    except (InvalidOperation, ValueError):
        return None

    if not hours_worked.is_finite() or hours_worked < 0:
        return None

    return hours_worked.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _resource_match_text(raw_text: Any) -> str:
    """Return normalized text used to rank Autotask resource matches."""

    normalized_text = RESOURCE_MATCH_TEXT_PATTERN.sub(" ", str(raw_text or "").strip().casefold())
    return " ".join(normalized_text.split())


def resource_name_for_display(raw_resource_name: str | None) -> str:
    """Return a resource name in first-name-first order for user-facing pages."""

    safe_resource_name = str(raw_resource_name or "").strip()
    if not safe_resource_name:
        return ""

    last_name, separator, first_name = safe_resource_name.partition(",")
    if separator and first_name.strip() and last_name.strip():
        return f"{first_name.strip()} {last_name.strip()}"[:MAX_RESOURCE_NAME_LENGTH]

    return safe_resource_name[:MAX_RESOURCE_NAME_LENGTH]


def _resource_display_name(first_name: str | None, last_name: str | None, resource_id: int) -> str:
    """Return the first-name-first resource label shown in authenticated pages."""

    safe_first_name = (first_name or "").strip()
    safe_last_name = (last_name or "").strip()
    if safe_first_name and safe_last_name:
        return f"{safe_first_name} {safe_last_name}"[:MAX_RESOURCE_NAME_LENGTH]
    if safe_last_name:
        return safe_last_name[:MAX_RESOURCE_NAME_LENGTH]
    if safe_first_name:
        return safe_first_name[:MAX_RESOURCE_NAME_LENGTH]

    return f"Resource {resource_id}"


def _contact_display_name(first_name: str | None, last_name: str | None, contact_id: int) -> str:
    """Return a human display label for an Autotask contact note author."""

    safe_first_name = (first_name or "").strip()
    safe_last_name = (last_name or "").strip()
    if safe_first_name and safe_last_name:
        return f"{safe_first_name} {safe_last_name}"[:MAX_TICKET_NOTE_AUTHOR_LENGTH]
    if safe_first_name:
        return safe_first_name[:MAX_TICKET_NOTE_AUTHOR_LENGTH]
    if safe_last_name:
        return safe_last_name[:MAX_TICKET_NOTE_AUTHOR_LENGTH]

    return f"Contact {contact_id}"


def _ticket_note_author_key(note_record: dict[str, Any]) -> tuple[str, int] | None:
    """Return the preferred safe author key for a TicketNotes record."""

    contact_id = _coerce_positive_autotask_id(
        note_record.get("createdByContactID")
        or note_record.get("createdbyContactID")
        or note_record.get("createdByContactId")
    )
    if contact_id is not None:
        return ("contact", contact_id)

    resource_id = _coerce_positive_autotask_id(
        note_record.get("creatorResourceID")
        or note_record.get("creatorresourceID")
        or note_record.get("createdByResourceID")
    )
    if resource_id is not None:
        return ("resource", resource_id)

    return None


def _ticket_note_author_fallback(author_key: tuple[str, int] | None) -> str | None:
    """Return a non-sensitive fallback label when author-name lookup is unavailable."""

    if author_key is None:
        return None
    author_kind, author_id = author_key
    if author_kind == "contact":
        return f"Contact {author_id}"
    if author_kind == "resource":
        return f"Resource {author_id}"
    return None


def _service_desk_role_label(role_id: int, *, role_name: str | None = None, is_default: bool = False) -> str:
    """Return display text for an active ResourceServiceDeskRoles role ID."""

    safe_role_name = _safe_optional_resource_text(role_name, max_length=MAX_SERVICE_DESK_ROLE_NAME_LENGTH)
    if safe_role_name and is_default:
        return f"{safe_role_name} (ID {role_id}, Autotask default)"
    label = f"{safe_role_name} (ID {role_id})" if safe_role_name else f"Role {role_id}"
    if is_default:
        return f"{label} (Autotask default)"
    return label


def _parse_autotask_datetime(raw_datetime: Any) -> datetime | None:
    """Parse an Autotask UTC datetime string for local sorting and audit context."""

    if raw_datetime in (None, ""):
        return None

    normalized_datetime = str(raw_datetime).strip()
    if not normalized_datetime:
        return None

    if normalized_datetime.endswith("Z"):
        normalized_datetime = f"{normalized_datetime[:-1]}+00:00"

    try:
        parsed_datetime = datetime.fromisoformat(normalized_datetime)
    except ValueError:
        return None

    return ensure_utc(parsed_datetime)


def _coerce_positive_autotask_id(raw_identifier: Any) -> int | None:
    """Return a positive Autotask identifier or None for malformed records."""

    try:
        coerced_identifier = int(raw_identifier)
    except (TypeError, ValueError):
        return None

    if coerced_identifier <= 0:
        return None

    return coerced_identifier


def _is_autotask_truthy(raw_value: Any) -> bool:
    """Return whether an Autotask boolean-like field represents true."""

    if raw_value is True:
        return True
    if isinstance(raw_value, str):
        return raw_value.strip().lower() == "true"

    return False


def _chunked_autotask_ids(autotask_ids: list[int]) -> list[list[int]]:
    """Return chunks that fit Autotask's documented list-query limits."""

    ordered_unique_ids = list(dict.fromkeys(autotask_ids))
    return [
        ordered_unique_ids[start_index : start_index + MAX_AUTOTASK_IN_FILTER_VALUES]
        for start_index in range(0, len(ordered_unique_ids), MAX_AUTOTASK_IN_FILTER_VALUES)
    ]


def build_autotask_summary_notes(job: Job) -> str:
    """Return the Autotask notes with the hidden work-location prefix applied."""

    work_location = _work_location_for_job(job)
    _submitted_work_location, raw_summary_notes = split_autotask_summary_notes(
        job.summary_notes or job.description_text,
        work_location,
    )
    prefix = WORK_LOCATION_SUMMARY_PREFIXES[work_location]

    return f"{prefix} {raw_summary_notes}".strip()


def build_ticket_note_description(job: Job) -> str:
    """Return the customer-visible Autotask TicketNotes description."""

    return str(job.summary_notes or job.description_text or "").strip()


def _append_to_resolution_for_job(job: Job) -> bool:
    """Return the local append-to-resolution setting, defaulting old blanks on."""

    raw_append_to_resolution = getattr(job, "append_to_resolution", True)
    return True if raw_append_to_resolution is None else bool(raw_append_to_resolution)


def build_safe_ticket_note_snapshot(job: Job) -> dict[str, Any]:
    """Build a non-secret snapshot of local ticket-note data used for submission."""

    note_description = build_ticket_note_description(job)
    return {
        "job_id": job.id,
        "entry_type": EntryType.TICKET_NOTE.value,
        "ticket_number": job.ticket_number,
        "ticket_status": job.ticket_status.value if job.ticket_status else None,
        "noteTitleLength": len((job.note_title or "").strip()),
        "noteDescriptionLength": len(note_description),
        "publish": CUSTOMER_VISIBLE_TICKET_NOTE_PUBLISH_VALUE,
        "noteType": DEFAULT_TICKET_NOTE_TYPE,
        "appendToResolution": _append_to_resolution_for_job(job),
    }


def build_safe_submission_snapshot(job: Job) -> dict[str, Any]:
    """Build a non-secret snapshot of local job data used for submission."""

    if job.entry_type == EntryType.TICKET_NOTE:
        return build_safe_ticket_note_snapshot(job)

    summary_notes_for_autotask = build_autotask_summary_notes(job)
    return {
        "job_id": job.id,
        "entry_type": EntryType.TIME_ENTRY.value,
        "ticket_number": job.ticket_number,
        "ticket_status": job.ticket_status.value if job.ticket_status else None,
        "startDateTime": format_autotask_datetime(job.rounded_start_utc),
        "endDateTime": format_autotask_datetime(job.rounded_end_utc) if job.rounded_end_utc else None,
        "hoursWorked": str(_job_duration_hours(job)) if job.rounded_end_utc else None,
        "work_location": _work_location_for_job(job).value,
        "summaryNotesLength": len(summary_notes_for_autotask),
        "appendToResolution": _append_to_resolution_for_job(job),
    }


class MockAutotaskProvider(BaseAutotaskProvider):
    """Local provider that marks submissions successful without external calls."""

    provider_name = "mock"

    def submit_job(
        self,
        job: Job,
        *,
        resource_id: int,
        default_service_desk_role_id: int | None = None,
    ) -> AutotaskSubmissionResult:
        """Return a deterministic mock external ID for end-to-end tests."""

        snapshot = build_safe_submission_snapshot(job)
        snapshot["resourceID"] = resource_id
        snapshot["defaultServiceDeskRoleID"] = default_service_desk_role_id
        external_id_prefix = "mock-ticket-note" if job.entry_type == EntryType.TICKET_NOTE else "mock-time-entry"
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=f"{external_id_prefix}-{job.id}",
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_time_entry(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-entry update tests."""

        snapshot = build_safe_submission_snapshot(job)
        snapshot["operation"] = "update_time_entry"
        snapshot["external_id"] = external_id
        snapshot["resourceID"] = resource_id
        snapshot["previous_ticket_status"] = previous_ticket_status.value if previous_ticket_status else None
        snapshot["ticketStatusUpdateAttempted"] = job.ticket_status is not None
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_time_entry(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-entry delete tests."""

        snapshot = {
            "operation": "delete_time_entry",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
            "resourceID": resource_id,
        }
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_ticket_note(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-note update tests."""

        snapshot = build_safe_submission_snapshot(job)
        snapshot["operation"] = "update_ticket_note"
        snapshot["external_id"] = external_id
        snapshot["resourceID"] = resource_id
        snapshot["previous_ticket_status"] = previous_ticket_status.value if previous_ticket_status else None
        snapshot["ticketStatusUpdateAttempted"] = job.ticket_status is not None
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_ticket_note(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-note delete tests."""

        snapshot = {
            "operation": "delete_ticket_note",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
            "resourceID": resource_id,
        }
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def test_connectivity(self) -> AutotaskConnectivityResult:
        """Return a successful local-only result for tests and development."""

        return AutotaskConnectivityResult(
            provider=self.provider_name,
            available=True,
            summary="Mock Autotask provider is available for development and tests; no live API call was made.",
            tips=("Use AUTOTASK_PROVIDER=autotask for production so company and ticket data come from Autotask.",),
            checked_operations=("mock provider",),
        )

    def list_open_tickets_for_client(
        self,
        client_name: str,
        autotask_company_id: int | None = None,
        *,
        resource_id: int | None = None,
    ) -> list[AutotaskTicketOption]:
        """Return deterministic open ticket options for local review testing."""

        safe_client_name = client_name.strip()
        if not safe_client_name:
            raise AutotaskSubmissionError("Client name is required before searching Autotask tickets.")

        return [
            AutotaskTicketOption(
                ticket_number="T20260616.0001",
                title=f"Mock open ticket for {safe_client_name}",
                description=f"Mock ticket description for {safe_client_name}.",
                status_label="In Progress",
                company_name=safe_client_name,
                detected_work_location=WorkLocation.REMOTE,
                work_location_label=WORK_LOCATION_DISPLAY_LABELS[WorkLocation.REMOTE],
                status_id=1,
            ),
            AutotaskTicketOption(
                ticket_number="T20260616.0002",
                title=f"Mock follow-up ticket for {safe_client_name}",
                description=f"Mock follow-up description for {safe_client_name}.",
                status_label="Follow Up",
                company_name=safe_client_name,
                detected_work_location=WorkLocation.ON_SITE,
                work_location_label=WORK_LOCATION_DISPLAY_LABELS[WorkLocation.ON_SITE],
                status_id=4,
            ),
        ]

    def list_ticket_notes(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketNote]:
        """Return deterministic ticket notes for local overlay testing."""

        safe_ticket_number = ticket_number.strip().upper()
        if not safe_ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before searching Autotask ticket notes.")

        return [
            AutotaskTicketNote(
                note_id=91002,
                title="Technician update",
                description="Previous technician confirmed the device was reachable from the LAN.",
                created_by="Previous Technician",
                created_at_utc=datetime(2026, 6, 16, 13, 30, tzinfo=UTC),
                note_type="Mock",
                publish=1,
            ),
            AutotaskTicketNote(
                note_id=91001,
                title=f"Mock ticket note for {safe_ticket_number}",
                description="Customer reported the issue before work started.",
                created_by="Customer Contact",
                created_at_utc=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
                updated_at_utc=datetime(2026, 6, 16, 12, 15, tzinfo=UTC),
                note_type="Mock",
                publish=1,
            ),
        ]

    def list_ticket_time_entries(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketTimeEntry]:
        """Return deterministic ticket time entries for local overlay testing."""

        safe_ticket_number = ticket_number.strip().upper()
        if not safe_ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before searching Autotask time entries.")

        return [
            AutotaskTicketTimeEntry(
                time_entry_id=81002,
                resource_name="Test Technician",
                start_at_utc=datetime(2026, 6, 29, 17, 30, tzinfo=UTC),
                end_at_utc=datetime(2026, 6, 29, 18, 15, tzinfo=UTC),
                hours_worked=Decimal("0.7500"),
                summary_notes="Remote. Confirmed backup job status and verified customer access.",
            ),
            AutotaskTicketTimeEntry(
                time_entry_id=81001,
                resource_name="Prior Engineer",
                start_at_utc=datetime(2026, 6, 28, 14, 0, tzinfo=UTC),
                end_at_utc=datetime(2026, 6, 28, 14, 30, tzinfo=UTC),
                hours_worked=Decimal("0.5000"),
                summary_notes=f"Remote. Initial triage for {safe_ticket_number}.",
            ),
        ]

    def search_companies(self, query_text: str, *, resource_id: int | None = None) -> list[AutotaskCompanyOption]:
        """Return deterministic company options for local autocomplete testing."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_COMPANY_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 3 characters before searching Autotask companies.")

        normalized_query_text = safe_query_text.casefold()
        return [
            company_option
            for company_option in MOCK_COMPANY_OPTIONS
            if normalized_query_text in company_option.company_name.casefold()
        ]

    def get_company_by_id(self, company_id: int, *, resource_id: int | None = None) -> AutotaskCompanyOption | None:
        """Return deterministic selected-company records for local testing."""

        for company_option in MOCK_COMPANY_OPTIONS:
            if company_option.company_id == company_id:
                return company_option
        return None

    def search_resources(self, query_text: str) -> list[AutotaskResourceOption]:
        """Return deterministic resource options for local web-user setup."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_RESOURCE_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 2 characters before searching Autotask resources.")

        resource_options = [
            AutotaskResourceOption(
                resource_id=42,
                resource_name="Joe Blow",
                first_name="Joe",
                last_name="Blow",
                email="joe.blow@example.test",
            ),
            AutotaskResourceOption(
                resource_id=1,
                resource_name="Test Technician",
                first_name="Test",
                last_name="Technician",
                email="test.technician@example.test",
            ),
        ]
        normalized_query = _resource_match_text(safe_query_text)
        matching_options = [
            resource_option
            for resource_option in resource_options
            if any(
                normalized_query in _resource_match_text(resource_text)
                for resource_text in (
                    resource_option.resource_name,
                    f"{resource_option.first_name or ''} {resource_option.last_name or ''}",
                    f"{resource_option.last_name or ''} {resource_option.first_name or ''}",
                    resource_option.email,
                )
            )
        ]

        return matching_options[:MAX_RESOURCE_LOOKUP_RESULTS]

    def list_resource_service_desk_roles(self, resource_id: int) -> list[AutotaskServiceDeskRoleOption]:
        """Return deterministic service-desk role options for local web-user setup."""

        if resource_id <= 0:
            raise AutotaskSubmissionError("Autotask resource ID must be a positive number.")
        return [
            AutotaskServiceDeskRoleOption(
                role_id=8,
                name="Service Desk",
                label="Service Desk (ID 8, Autotask default)",
                is_default=True,
            ),
            AutotaskServiceDeskRoleOption(role_id=15, name="Field Technician", label="Field Technician (ID 15)"),
        ]

    def list_todays_service_calls_for_resource(
        self,
        resource_id: int,
        current_time_utc: datetime | None = None,
        local_service_date: date | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return deterministic service-call options for local mobile testing."""

        safe_current_time_utc = ensure_utc(current_time_utc or now_utc())
        selected_local_date = local_service_date or local_date_for(safe_current_time_utc)
        local_day_start_utc, _local_day_end_utc = local_day_bounds_utc(selected_local_date)
        first_start_utc = local_day_start_utc + timedelta(hours=12)
        first_end_utc = first_start_utc + timedelta(hours=1)
        second_start_utc = local_day_start_utc + timedelta(hours=14)
        second_end_utc = second_start_utc + timedelta(hours=1)
        onsite_details = "Onsite service call for scheduled firewall replacement."
        remote_details = "Remote follow-up service call for backup verification."
        onsite_work_location = detect_work_location_from_service_call_details(onsite_details)
        remote_work_location = detect_work_location_from_service_call_details(remote_details)
        return [
            AutotaskServiceCallOption(
                service_call_id=6001,
                service_call_ticket_id=6101,
                service_call_name="Mock onsite service call",
                service_call_details=onsite_details,
                detected_work_location=onsite_work_location,
                work_location_label=work_location_label_for_detection(onsite_work_location),
                ticket_number="T20260616.0001",
                ticket_title="Mock open ticket for Scheduled Service Client",
                ticket_description="Mock ticket description from scheduled service call.",
                ticket_status_label="New",
                client_name="Scheduled Service Client",
                autotask_company_id=1001,
                start_datetime_utc=first_start_utc,
                end_datetime_utc=first_end_utc,
            ),
            AutotaskServiceCallOption(
                service_call_id=6002,
                service_call_ticket_id=6102,
                service_call_name="Mock remote service call",
                service_call_details=remote_details,
                detected_work_location=remote_work_location,
                work_location_label=work_location_label_for_detection(remote_work_location),
                ticket_number="T20260616.0002",
                ticket_title="Mock follow-up ticket for Scheduled Service Client",
                ticket_description="Mock follow-up description from scheduled service call.",
                ticket_status_label="In Progress",
                client_name="Scheduled Service Client",
                autotask_company_id=1001,
                start_datetime_utc=second_start_utc,
                end_datetime_utc=second_end_utc,
            ),
        ]


class LiveAutotaskProvider(BaseAutotaskProvider):
    """Autotask REST API provider for reviewed TimeEntries and TicketNotes."""

    provider_name = "autotask"

    def __init__(self, application_settings: Settings) -> None:
        """Store settings and validate required live Autotask values."""

        self.application_settings = application_settings
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Ensure live Autotask API access has every required secret."""

        required_values = {
            "AUTOTASK_BASE_URL": self.application_settings.autotask_base_url,
            "AUTOTASK_USERNAME": self.application_settings.autotask_username,
            "AUTOTASK_SECRET": self.application_settings.autotask_secret,
            "AUTOTASK_API_INTEGRATION_CODE": self.application_settings.autotask_api_integration_code,
        }
        missing_values = [name for name, value in required_values.items() if value in (None, "")]
        if missing_values:
            raise AutotaskSubmissionError(f"Missing live Autotask settings: {', '.join(missing_values)}")

    def _headers(self) -> dict[str, str]:
        """Return required Autotask REST API headers without logging them."""

        return {
            "ApiIntegrationCode": self.application_settings.autotask_api_integration_code or "",
            "UserName": self.application_settings.autotask_username or "",
            "Secret": self.application_settings.autotask_secret or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _client(self, timeout_seconds: float = 30.0) -> httpx.Client:
        """Return a short-lived HTTP client for Autotask calls."""

        base_url = (self.application_settings.autotask_base_url or "").rstrip("/")
        return httpx.Client(
            base_url=base_url,
            headers=self._headers(),
            timeout=timeout_seconds,
        )

    def _api_request(
        self,
        client: httpx.Client,
        method: str,
        endpoint_path: str,
        action_description: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Run one Autotask request and update cached health from transport state."""

        try:
            request_method = getattr(client, method.lower())
            response = request_method(endpoint_path, **kwargs)
        except httpx.HTTPError:
            record_autotask_api_failure(
                f"{action_description} could not reach the Autotask API.",
                operation=action_description,
            )
            raise

        if response.status_code < 400:
            record_autotask_api_success(operation=action_description)
        return response

    def _cache_namespace(self) -> str:
        """Return the non-secret namespace used for tenant-specific cache keys."""

        return (self.application_settings.autotask_base_url or "").rstrip("/")

    def _open_ticket_selection_cache_key(
        self,
        client_name: str,
        autotask_company_id: int | None,
    ) -> tuple[str, str, int | None]:
        """Return the cache key for a recently displayed open-ticket list."""

        normalized_client_name = client_name.strip().casefold()
        return (self._cache_namespace(), normalized_client_name, autotask_company_id)

    def _resource_search_cache_key(self, query_text: str) -> tuple[str, str]:
        """Return the cache key for resource directory lookup results."""

        return (self._cache_namespace(), _resource_match_text(query_text))

    def _service_call_selection_cache_key(
        self,
        resource_id: int,
        local_day_start_utc: datetime,
        local_day_end_utc: datetime,
    ) -> tuple[str, int, str, str]:
        """Return the cache key for a selected-day service-call start list."""

        return (
            self._cache_namespace(),
            resource_id,
            format_autotask_datetime(local_day_start_utc),
            format_autotask_datetime(local_day_end_utc),
        )

    def _raise_for_safe_response(self, response: httpx.Response, action_description: str) -> None:
        """Raise a safe Autotask error without exposing headers or secrets."""

        if response.status_code < 400:
            return

        safe_error_detail = self._safe_response_error_detail(response)
        if safe_error_detail:
            record_autotask_api_failure(
                f"{action_description} failed with Autotask HTTP {response.status_code}: {safe_error_detail}",
                operation=action_description,
            )
            raise AutotaskSubmissionError(
                f"{action_description} failed with Autotask HTTP {response.status_code}: {safe_error_detail}"
            )

        record_autotask_api_failure(
            f"{action_description} failed with Autotask HTTP {response.status_code}.",
            operation=action_description,
        )
        raise AutotaskSubmissionError(f"{action_description} failed with Autotask HTTP {response.status_code}.")

    def _safe_response_error_detail(self, response: httpx.Response) -> str | None:
        """Return a bounded Autotask error detail when the body is safe to show."""

        try:
            response_payload = response.json()
        except ValueError:
            return None

        # Autotask commonly returns a top-level `errors` list. Those entries
        # contain operational failure reasons, not request headers or secrets.
        if not isinstance(response_payload, dict):
            return None

        raw_errors = response_payload.get("errors") or response_payload.get("Errors")
        if isinstance(raw_errors, list):
            safe_error_messages: list[str] = []
            for error_message in raw_errors:
                if isinstance(error_message, dict):
                    raw_error_text = (
                        error_message.get("message")
                        or error_message.get("Message")
                        or error_message.get("detail")
                        or error_message.get("Detail")
                        or error_message.get("description")
                        or error_message.get("Description")
                    )
                else:
                    raw_error_text = error_message

                safe_error_text = str(raw_error_text or "").strip()
                if safe_error_text:
                    safe_error_messages.append(safe_error_text)
            if safe_error_messages:
                return "; ".join(safe_error_messages)[:AUTOTASK_SAFE_ERROR_TEXT_LIMIT]

        raw_message = (
            response_payload.get("message")
            or response_payload.get("Message")
            or response_payload.get("detail")
            or response_payload.get("Detail")
            or response_payload.get("title")
            or response_payload.get("Title")
            or response_payload.get("exceptionMessage")
            or response_payload.get("ExceptionMessage")
        )
        if raw_message:
            return str(raw_message).strip()[:AUTOTASK_SAFE_ERROR_TEXT_LIMIT]

        return None

    def _query_paginated_items(
        self,
        client: httpx.Client,
        *,
        endpoint_path: str,
        query_payload: dict[str, Any],
        action_description: str,
        max_records: int = AUTOTASK_MAX_RECORDS_PER_PAGE,
        follow_pagination: bool = True,
    ) -> list[dict[str, Any]]:
        """Return all Autotask query items using MaxRecords and next-page URLs."""

        paged_query_payload = dict(query_payload)
        paged_query_payload["MaxRecords"] = max(1, min(max_records, AUTOTASK_MAX_RECORDS_PER_PAGE))

        collected_items: list[dict[str, Any]] = []
        response = self._api_request(
            client,
            "POST",
            endpoint_path,
            action_description,
            json=paged_query_payload,
        )
        page_number = 1

        while True:
            self._raise_for_safe_response(response, action_description)
            response_payload = response.json()
            page_items = (response_payload.get("items") or response_payload.get("Item") or []) if isinstance(response_payload, dict) else []
            if isinstance(page_items, list):
                collected_items.extend(item for item in page_items if isinstance(item, dict))

            page_details = response_payload.get("pageDetails") if isinstance(response_payload, dict) else None
            next_page_url = page_details.get("nextPageUrl") if isinstance(page_details, dict) else None
            if not next_page_url or not follow_pagination:
                break

            if page_number >= AUTOTASK_MAX_PAGINATED_PAGES:
                raise AutotaskSubmissionError(
                    f"{action_description} returned more than {AUTOTASK_MAX_PAGINATED_PAGES} pages; narrow the search."
                )

            # Autotask's POST query pagination returns a nextPageUrl, but the
            # follow-up request must still use POST with the original query
            # body. Using GET returns HTTP 405 for POST query resources.
            response = self._api_request(
                client,
                "POST",
                str(next_page_url),
                action_description,
                json=paged_query_payload,
            )
            page_number += 1

        return collected_items

    def _query_todays_service_calls(
        self,
        client: httpx.Client,
        *,
        local_day_start_utc: datetime,
        local_day_end_utc: datetime,
    ) -> list[dict[str, Any]]:
        """Return service calls whose scheduled start falls within the local day."""

        query_payload = {
            "IncludeFields": ["id", "description", "startDateTime", "endDateTime", "companyID"],
            "filter": [
                {
                    "op": "gte",
                    "field": "startDateTime",
                    "value": format_autotask_datetime(local_day_start_utc),
                },
                {
                    "op": "lt",
                    "field": "startDateTime",
                    "value": format_autotask_datetime(local_day_end_utc),
                },
            ],
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/ServiceCalls/query",
            query_payload=query_payload,
            action_description="Autotask service-call lookup",
        )

    def _query_service_call_tickets_for_service_calls(
        self,
        client: httpx.Client,
        service_call_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Return ticket links for the supplied service-call IDs."""

        service_call_ticket_records: list[dict[str, Any]] = []
        for service_call_id_chunk in _chunked_autotask_ids(service_call_ids):
            query_payload = {
                "IncludeFields": ["id", "serviceCallID", "ticketID"],
                "filter": [
                    {
                        "op": "in",
                        "field": "serviceCallID",
                        "value": service_call_id_chunk,
                    }
                ],
            }
            service_call_ticket_records.extend(
                self._query_paginated_items(
                    client,
                    endpoint_path="/ServiceCallTickets/query",
                    query_payload=query_payload,
                    action_description="Autotask service-call ticket lookup",
                )
            )

        return service_call_ticket_records

    def _query_service_call_ticket_resources(
        self,
        client: httpx.Client,
        *,
        resource_id: int,
        service_call_ticket_ids: list[int],
    ) -> list[dict[str, Any]]:
        """Return service-call ticket resource assignments for one Autotask resource."""

        service_call_ticket_resource_records: list[dict[str, Any]] = []
        for service_call_ticket_id_chunk in _chunked_autotask_ids(service_call_ticket_ids):
            query_payload = {
                "IncludeFields": ["id", "resourceID", "serviceCallTicketID"],
                "filter": [
                    {
                        "op": "eq",
                        "field": "resourceID",
                        "value": resource_id,
                    },
                    {
                        "op": "in",
                        "field": "serviceCallTicketID",
                        "value": service_call_ticket_id_chunk,
                    },
                ],
            }
            service_call_ticket_resource_records.extend(
                self._query_paginated_items(
                    client,
                    endpoint_path="/ServiceCallTicketResources/query",
                    query_payload=query_payload,
                    action_description="Autotask service-call resource lookup",
                )
            )

        return service_call_ticket_resource_records

    def _query_tickets_by_ids(self, client: httpx.Client, ticket_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Return safe ticket records keyed by Autotask ticket ID."""

        ticket_records_by_id: dict[int, dict[str, Any]] = {}
        for ticket_id_chunk in _chunked_autotask_ids(ticket_ids):
            query_payload = {
                "IncludeFields": ["id", "ticketNumber", "title", "description", "companyID", "status", "source"],
                "filter": [
                    {
                        "op": "in",
                        "field": "id",
                        "value": ticket_id_chunk,
                    }
                ],
            }
            ticket_records = self._query_paginated_items(
                client,
                endpoint_path="/Tickets/query",
                query_payload=query_payload,
                action_description="Autotask service-call ticket detail lookup",
            )
            for ticket_record in ticket_records:
                ticket_id = _coerce_positive_autotask_id(ticket_record.get("id"))
                if ticket_id is not None:
                    ticket_records_by_id[ticket_id] = ticket_record

        return ticket_records_by_id

    def _query_companies_by_ids(
        self,
        client: httpx.Client,
        company_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        """Return active Autotask company records keyed by company ID."""

        company_records_by_id: dict[int, dict[str, Any]] = {}
        missing_company_ids: list[int] = []
        for company_id in dict.fromkeys(company_ids):
            cache_key = (self._cache_namespace(), company_id)
            cached_company = _get_cached_value(_COMPANY_ID_CACHE, cache_key)
            if isinstance(cached_company, dict):
                company_records_by_id[company_id] = cached_company
            else:
                missing_company_ids.append(company_id)

        for company_id_chunk in _chunked_autotask_ids(missing_company_ids):
            query_payload = {
                "IncludeFields": ["id", "companyName", "isActive"],
                "filter": [
                    {
                        "op": "in",
                        "field": "id",
                        "value": company_id_chunk,
                    }
                ],
            }
            company_records = self._query_paginated_items(
                client,
                endpoint_path="/Companies/query",
                query_payload=query_payload,
                action_description="Autotask service-call company lookup",
            )
            for company_record in company_records:
                company_id = _coerce_positive_autotask_id(company_record.get("id"))
                if company_id is None or not company_record.get("isActive", True):
                    continue
                company_records_by_id[company_id] = company_record
                _set_cached_value(
                    _COMPANY_ID_CACHE,
                    (self._cache_namespace(), company_id),
                    company_record,
                    COMPANY_CACHE_TTL_SECONDS,
                )

        return company_records_by_id

    def _build_service_call_options(
        self,
        *,
        service_call_records: list[dict[str, Any]],
        service_call_ticket_records: list[dict[str, Any]],
        service_call_ticket_resource_records: list[dict[str, Any]],
        ticket_records_by_id: dict[int, dict[str, Any]],
        company_records_by_id: dict[int, dict[str, Any]],
        status_labels: dict[int, str],
        source_labels: dict[int, str],
    ) -> list[AutotaskServiceCallOption]:
        """Build mobile-safe service-call choices from related Autotask rows."""

        service_call_records_by_id = {
            service_call_id: service_call_record
            for service_call_record in service_call_records
            if (service_call_id := _coerce_positive_autotask_id(service_call_record.get("id"))) is not None
        }
        assigned_service_call_ticket_ids = {
            service_call_ticket_id
            for resource_record in service_call_ticket_resource_records
            if (service_call_ticket_id := _coerce_positive_autotask_id(resource_record.get("serviceCallTicketID"))) is not None
        }
        service_call_tickets_by_service_call_id: dict[int, list[dict[str, Any]]] = {}
        for service_call_ticket_record in service_call_ticket_records:
            service_call_ticket_id = _coerce_positive_autotask_id(service_call_ticket_record.get("id"))
            service_call_id = _coerce_positive_autotask_id(service_call_ticket_record.get("serviceCallID"))
            if service_call_ticket_id is None or service_call_id is None or service_call_ticket_id not in assigned_service_call_ticket_ids:
                continue
            service_call_tickets_by_service_call_id.setdefault(service_call_id, []).append(service_call_ticket_record)

        sorted_service_calls = sorted(
            service_call_records_by_id.values(),
            key=lambda service_call_record: (
                _parse_autotask_datetime(service_call_record.get("startDateTime")) or datetime.max.replace(tzinfo=UTC),
                _coerce_positive_autotask_id(service_call_record.get("id")) or 0,
            ),
        )
        service_call_options: list[AutotaskServiceCallOption] = []
        for service_call_record in sorted_service_calls:
            service_call_id = _coerce_positive_autotask_id(service_call_record.get("id"))
            if service_call_id is None:
                continue

            service_call_detail_text = _safe_service_call_text(
                service_call_record.get("description"),
                "",
                MAX_SERVICE_CALL_DETAIL_LENGTH,
            )
            service_call_details = service_call_detail_text or None
            service_call_name = _safe_service_call_text(
                service_call_record.get("name") or service_call_record.get("title") or service_call_detail_text,
                f"Service call {service_call_id}",
                MAX_SERVICE_CALL_NAME_LENGTH,
            )
            start_datetime_utc = _parse_autotask_datetime(service_call_record.get("startDateTime"))
            end_datetime_utc = _parse_autotask_datetime(service_call_record.get("endDateTime"))

            for service_call_ticket_record in service_call_tickets_by_service_call_id.get(service_call_id, []):
                service_call_ticket_id = _coerce_positive_autotask_id(service_call_ticket_record.get("id"))
                ticket_id = _coerce_positive_autotask_id(service_call_ticket_record.get("ticketID"))
                if service_call_ticket_id is None or ticket_id is None:
                    continue

                ticket_record = ticket_records_by_id.get(ticket_id)
                if ticket_record is None:
                    continue

                ticket_number = str(ticket_record.get("ticketNumber") or "").strip()
                if not ticket_number:
                    continue

                raw_status_id = ticket_record.get("status")
                try:
                    status_id = int(raw_status_id)
                except (TypeError, ValueError):
                    status_id = -1

                company_id = (
                    _coerce_positive_autotask_id(service_call_record.get("companyID"))
                    or _coerce_positive_autotask_id(ticket_record.get("companyID"))
                )
                if company_id is None:
                    continue

                company_record = company_records_by_id.get(company_id)
                client_name = _safe_service_call_text(
                    company_record.get("companyName") if company_record else None,
                    f"Company {company_id}",
                    120,
                )
                ticket_description = _safe_service_call_text(ticket_record.get("description"), "", 8000) or None
                detected_work_location = detect_work_location_from_text_or_ticket_source(
                    service_call_details,
                    _ticket_source_label(ticket_record, source_labels),
                )
                service_call_options.append(
                    AutotaskServiceCallOption(
                        service_call_id=service_call_id,
                        service_call_ticket_id=service_call_ticket_id,
                        service_call_name=service_call_name,
                        service_call_details=service_call_details,
                        detected_work_location=detected_work_location,
                        work_location_label=work_location_label_for_detection(detected_work_location),
                        ticket_number=ticket_number,
                        ticket_title=_safe_service_call_text(ticket_record.get("title"), "Untitled ticket", 240),
                        ticket_description=ticket_description,
                        ticket_status_label=status_labels.get(status_id, str(raw_status_id or "Unknown")),
                        client_name=client_name,
                        autotask_company_id=company_id,
                        start_datetime_utc=start_datetime_utc,
                        end_datetime_utc=end_datetime_utc,
                    )
                )
                if len(service_call_options) >= MAX_SERVICE_CALL_LOOKUP_RESULTS:
                    return service_call_options

        return service_call_options

    def _workflow_configuration_gaps(self) -> list[str]:
        """Return missing settings that would prevent the full Autotask workflow."""

        required_workflow_values = {
            "AUTOTASK_STATUS_IN_PROGRESS_ID": self.application_settings.autotask_status_in_progress_id,
            "AUTOTASK_STATUS_WAITING_CUSTOMER_ID": self.application_settings.autotask_status_waiting_customer_id,
            "AUTOTASK_STATUS_WAITING_PARTS_ID": self.application_settings.autotask_status_waiting_parts_id,
            "AUTOTASK_STATUS_FOLLOW_UP_ID": self.application_settings.autotask_status_follow_up_id,
            "AUTOTASK_STATUS_COMPLETE_ID": self.application_settings.autotask_status_complete_id,
        }
        return [setting_name for setting_name, setting_value in required_workflow_values.items() if setting_value is None]

    def _query_tickets_for_connectivity(self, client: httpx.Client) -> None:
        """Confirm the Tickets query endpoint is reachable without exposing data."""

        query_payload = {"filter": [{"op": "exist", "field": "id"}]}
        self._query_single_page_for_connectivity(
            client,
            endpoint_path="/Tickets/query",
            query_payload=query_payload,
            action_description="Autotask ticket connectivity query",
        )

    def _query_companies_for_connectivity(self, client: httpx.Client) -> None:
        """Confirm the Companies query endpoint is reachable without exposing data."""

        # The app needs live Companies query access for mobile client selection.
        # Using a one-page existence probe avoids assuming any specific company
        # ID exists and avoids walking through customer data during diagnostics.
        query_payload = {"filter": [{"op": "exist", "field": "id"}]}
        self._query_single_page_for_connectivity(
            client,
            endpoint_path="/Companies/query",
            query_payload=query_payload,
            action_description="Autotask company connectivity query",
        )

    def _query_single_page_for_connectivity(
        self,
        client: httpx.Client,
        *,
        endpoint_path: str,
        query_payload: dict[str, Any],
        action_description: str,
    ) -> None:
        """Run one bounded query page to prove an Autotask endpoint is usable."""

        connectivity_query_payload = dict(query_payload)
        connectivity_query_payload["MaxRecords"] = 1
        response = self._api_request(
            client,
            "POST",
            endpoint_path,
            action_description,
            json=connectivity_query_payload,
        )
        self._raise_for_safe_response(response, action_description)
        response.json()

    def _tips_for_remote_failure(self, exc: Exception, failed_operation: str | None = None) -> tuple[str, ...]:
        """Return safe troubleshooting tips for a failed live Autotask check."""

        error_message = str(exc)
        if "adequate permissions" in error_message:
            return (
                f"Grant the Autotask API user's resource security level permission to read {failed_operation or 'the failed entity'} through the REST API.",
                "Retest the debug page after changing Autotask permissions; no Job Logger secret changes are needed for this failure.",
                "The same API user can read some metadata, so credential discovery may still succeed while workflow entity queries fail.",
            )

        if "HTTP 500" in error_message and failed_operation == "companies":
            return (
                "Autotask accepted the base URL and credentials but failed the Companies query used by mobile client lookup.",
                "Confirm the API user's security level can read Companies/Organizations through the Autotask REST API.",
                "Run scripts/discover_autotask_ids.py again and check its workflow preflight section; "
                "ID discovery can succeed while Companies query access still fails.",
            )

        if "HTTP 500" in error_message and failed_operation == "tickets":
            return (
                "Autotask accepted the base URL and credentials but failed the Tickets query used by open-ticket lookup and submission.",
                "Confirm the API user's security level can read Tickets through the Autotask REST API.",
                "If permissions look correct, retest later or open an Autotask support case because the tenant returned a server-side 500.",
            )

        if isinstance(exc, httpx.TimeoutException):
            return (
                "Confirm the Docker host can reach the internet and Autotask is not blocked by firewall or DNS policy.",
                "Confirm AUTOTASK_BASE_URL points to your tenant's REST base URL and not the interactive web portal URL.",
            )

        if isinstance(exc, httpx.ConnectError):
            return (
                "Confirm AUTOTASK_BASE_URL is spelled correctly and includes the tenant REST path ending in /ATServicesRest/V1.0.",
                "Confirm the Docker host has DNS and outbound HTTPS access.",
            )

        if "HTTP 401" in error_message or "HTTP 403" in error_message:
            return (
                "Verify AUTOTASK_USERNAME is the API user's Username (key), not the human login email.",
                "Verify AUTOTASK_SECRET and AUTOTASK_API_INTEGRATION_CODE match the active Autotask API user.",
                "Confirm the API user is active and has permission to read Companies, read Tickets, and create TimeEntries.",
            )

        if "HTTP 404" in error_message:
            return (
                "Confirm AUTOTASK_BASE_URL includes the correct tenant zone and /ATServicesRest/V1.0 path.",
                "Confirm the configured Autotask zone URL is the REST API URL, not the SOAP or browser URL.",
            )

        if "HTTP 429" in error_message:
            return (
                "Autotask is rate limiting requests; wait and try again before starting new jobs.",
                "Check whether another process is repeatedly querying Autotask with the same API user.",
            )

        return (
            "Verify the Autotask API user, integration code, tenant REST base URL, and outbound HTTPS connectivity.",
            "Use the Autotask discovery script after connectivity is restored to confirm tenant-specific IDs.",
        )

    def test_connectivity(self) -> AutotaskConnectivityResult:
        """Verify live Autotask settings and the endpoints required by this app."""

        workflow_gaps = self._workflow_configuration_gaps()
        if workflow_gaps:
            return AutotaskConnectivityResult(
                provider=self.provider_name,
                available=False,
                summary=f"Autotask workflow configuration is incomplete: {', '.join(workflow_gaps)}.",
                tips=(
                    "Fill the listed AUTOTASK_* values in .env and recreate the app container.",
                    "Use scripts/discover_autotask_ids.py to look up ticket status IDs after API credentials work.",
                ),
                checked_operations=("configuration",),
                failed_operation="configuration",
            )

        checked_operations: list[str] = ["configuration"]
        failed_operation = "companies"
        try:
            with self._client(timeout_seconds=10.0) as client:
                self._query_companies_for_connectivity(client)
                checked_operations.append("companies")
                failed_operation = "ticket status metadata"
                self._query_ticket_status_labels(client)
                checked_operations.append("ticket status metadata")
                failed_operation = "tickets"
                self._query_tickets_for_connectivity(client)
                checked_operations.append("tickets")
        except (httpx.HTTPError, ValueError, AutotaskSubmissionError) as exc:
            return AutotaskConnectivityResult(
                provider=self.provider_name,
                available=False,
                summary=f"Autotask API check failed during {failed_operation}: {exc}",
                tips=self._tips_for_remote_failure(exc, failed_operation),
                checked_operations=tuple(checked_operations),
                failed_operation=failed_operation,
            )

        return AutotaskConnectivityResult(
            provider=self.provider_name,
            available=True,
            summary="Autotask API connection succeeded for company lookup, ticket status metadata, and ticket lookup.",
            tips=("Autotask is available for starting new jobs.",),
            checked_operations=tuple(checked_operations),
        )

    def _query_ticket_picklist_labels(
        self,
        client: httpx.Client,
        *,
        field_name: str,
        cache_store: dict[str, _AutotaskCacheEntry],
        action_description: str,
    ) -> dict[int, str]:
        """Return one Autotask Tickets picklist field as ID-to-label mappings."""

        cache_key = self._cache_namespace()
        cached_picklist_labels = _get_cached_value(cache_store, cache_key)
        if isinstance(cached_picklist_labels, dict):
            return cached_picklist_labels

        response = self._api_request(
            client,
            "GET",
            f"/Tickets/entityInformation/fields/{field_name}",
            action_description,
        )
        if response.status_code == 404:
            response = self._api_request(
                client,
                "GET",
                "/Tickets/entityInformation/fields",
                action_description,
            )
        self._raise_for_safe_response(response, action_description)

        response_payload = response.json()
        picklist_field: dict[str, Any] | None = None
        if isinstance(response_payload, dict) and "picklistValues" in response_payload:
            picklist_field = response_payload
        else:
            fields = response_payload.get("fields") if isinstance(response_payload, dict) else response_payload
            if isinstance(fields, list):
                for field_record in fields:
                    if isinstance(field_record, dict) and field_record.get("name") == field_name:
                        picklist_field = field_record
                        break

        if picklist_field is None:
            _set_cached_value(cache_store, cache_key, {})
            return {}

        picklist_values = picklist_field.get("picklistValues") or picklist_field.get("PicklistValues") or []
        picklist_labels: dict[int, str] = {}
        if not isinstance(picklist_values, list):
            _set_cached_value(cache_store, cache_key, picklist_labels)
            return picklist_labels

        for picklist_value in picklist_values:
            if not isinstance(picklist_value, dict):
                continue

            raw_picklist_id = picklist_value.get("value") or picklist_value.get("id")
            picklist_label = picklist_value.get("label") or picklist_value.get("name")
            if raw_picklist_id is None or picklist_label is None:
                continue

            try:
                picklist_labels[int(raw_picklist_id)] = str(picklist_label)
            except (TypeError, ValueError):
                continue

        _set_cached_value(cache_store, cache_key, picklist_labels)
        return picklist_labels

    def _query_ticket_status_labels(self, client: httpx.Client) -> dict[int, str]:
        """Return Autotask Tickets.status picklist values as ID-to-label mappings."""

        return self._query_ticket_picklist_labels(
            client,
            field_name="status",
            cache_store=_TICKET_STATUS_CACHE,
            action_description="Autotask ticket status metadata query",
        )

    def _query_ticket_source_labels(self, client: httpx.Client) -> dict[int, str]:
        """Return Autotask Tickets.source picklist values as ID-to-label mappings."""

        return self._query_ticket_picklist_labels(
            client,
            field_name="source",
            cache_store=_TICKET_SOURCE_CACHE,
            action_description="Autotask ticket source metadata query",
        )

    def _query_ticket_source_labels_without_blocking_lookup(self, client: httpx.Client) -> dict[int, str]:
        """Return source labels when available without breaking ticket lookup."""

        try:
            return self._query_ticket_source_labels(client)
        except AutotaskSubmissionError:
            return {}

    def _query_companies_by_name(
        self,
        client: httpx.Client,
        client_name: str,
    ) -> list[dict[str, Any]]:
        """Return active Autotask companies whose names contain the job client name."""

        normalized_query_text = client_name.strip().casefold()
        cache_key = (self._cache_namespace(), normalized_query_text)
        cached_companies = _get_cached_value(_COMPANY_SEARCH_CACHE, cache_key)
        if isinstance(cached_companies, list) and cached_companies:
            return cached_companies[:MAX_COMPANY_MATCHES_FOR_TICKET_LOOKUP]

        query_payload = {"filter": [{"op": "contains", "field": "companyName", "value": client_name}]}
        companies = self._query_paginated_items(
            client,
            endpoint_path="/Companies/query",
            query_payload=query_payload,
            action_description="Autotask company lookup",
        )
        active_companies = [
            company
            for company in companies
            if isinstance(company, dict) and company.get("id") is not None and company.get("isActive", True)
        ]
        normalized_client_name = client_name.strip().casefold()
        active_companies.sort(
            key=lambda company: (
                str(company.get("companyName", "")).strip().casefold() != normalized_client_name,
                str(company.get("companyName", "")).casefold(),
            )
        )
        if active_companies:
            _set_cached_value(_COMPANY_SEARCH_CACHE, cache_key, active_companies, COMPANY_CACHE_TTL_SECONDS)
            for active_company in active_companies:
                try:
                    active_company_id = int(active_company["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                _set_cached_value(
                    _COMPANY_ID_CACHE,
                    (self._cache_namespace(), active_company_id),
                    active_company,
                    COMPANY_CACHE_TTL_SECONDS,
                )
        return active_companies[:MAX_COMPANY_MATCHES_FOR_TICKET_LOOKUP]

    def _query_company_by_id(
        self,
        client: httpx.Client,
        company_id: int,
    ) -> dict[str, Any] | None:
        """Return one active Autotask company by ID."""

        cache_key = (self._cache_namespace(), company_id)
        cached_company = _get_cached_value(_COMPANY_ID_CACHE, cache_key)
        if isinstance(cached_company, dict):
            return cached_company

        query_payload = {"filter": [{"op": "eq", "field": "id", "value": company_id}]}
        companies = self._query_paginated_items(
            client,
            endpoint_path="/Companies/query",
            query_payload=query_payload,
            action_description="Autotask company lookup",
        )

        for company in companies:
            if isinstance(company, dict) and company.get("id") is not None and company.get("isActive", True):
                _set_cached_value(_COMPANY_ID_CACHE, cache_key, company, COMPANY_CACHE_TTL_SECONDS)
                return company

        return None

    def _resource_name_terms(self, query_text: str) -> tuple[str, str | None, str | None]:
        """Return clean resource search text plus inferred first and last names."""

        safe_query_text = " ".join(query_text.strip().split())
        if "," in safe_query_text:
            raw_last_name, raw_first_name = safe_query_text.split(",", 1)
            first_name = raw_first_name.strip().split()[0] if raw_first_name.strip() else None
            last_name = raw_last_name.strip() or None
            return safe_query_text, first_name, last_name

        name_parts = safe_query_text.split()
        if len(name_parts) >= 2:
            return safe_query_text, name_parts[0], name_parts[-1]
        if name_parts:
            return safe_query_text, name_parts[0], name_parts[0]

        return safe_query_text, None, None

    def _query_resources_by_filters(self, client: httpx.Client, filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return one bounded page of Autotask resources for a filter set."""

        query_payload = {
            "IncludeFields": ["id", "firstName", "lastName", "email"],
            "filter": filters,
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/Resources/query",
            query_payload=query_payload,
            action_description="Autotask resource lookup",
            max_records=MAX_RESOURCE_LOOKUP_RESULTS,
            follow_pagination=False,
        )

    def _query_resources_by_name(self, client: httpx.Client, query_text: str) -> list[dict[str, Any]]:
        """Return likely Autotask Resource records for a human-entered name."""

        safe_query_text, first_name, last_name = self._resource_name_terms(query_text)
        cache_key = self._resource_search_cache_key(safe_query_text)
        cached_resources = _get_cached_value(_RESOURCE_SEARCH_CACHE, cache_key)
        if isinstance(cached_resources, list) and cached_resources:
            return cached_resources[:MAX_RESOURCE_LOOKUP_RESULTS]

        candidate_filter_sets: list[list[dict[str, Any]]] = []
        if first_name and last_name and _resource_match_text(first_name) != _resource_match_text(last_name):
            candidate_filter_sets.append(
                [
                    {"op": "contains", "field": "lastName", "value": last_name},
                    {"op": "contains", "field": "firstName", "value": first_name},
                ]
            )
        if last_name:
            candidate_filter_sets.append([{"op": "contains", "field": "lastName", "value": last_name}])
        if first_name:
            candidate_filter_sets.append([{"op": "contains", "field": "firstName", "value": first_name}])

        resource_records_by_id: dict[int, dict[str, Any]] = {}
        seen_filter_keys: set[tuple[tuple[str, str, str], ...]] = set()
        for filters in candidate_filter_sets:
            filter_key = tuple(
                (str(resource_filter["field"]), str(resource_filter["op"]), str(resource_filter["value"]).casefold())
                for resource_filter in filters
            )
            if filter_key in seen_filter_keys:
                continue
            seen_filter_keys.add(filter_key)

            for resource_record in self._query_resources_by_filters(client, filters):
                resource_id = _coerce_positive_autotask_id(resource_record.get("id"))
                if resource_id is None:
                    continue
                resource_records_by_id.setdefault(resource_id, resource_record)
                if len(resource_records_by_id) >= MAX_RESOURCE_LOOKUP_RESULTS:
                    break

            if len(resource_records_by_id) >= MAX_RESOURCE_LOOKUP_RESULTS:
                break

        resource_records = list(resource_records_by_id.values())
        resource_records.sort(key=lambda resource_record: self._resource_record_rank(resource_record, safe_query_text))
        if resource_records:
            _set_cached_value(_RESOURCE_SEARCH_CACHE, cache_key, resource_records)

        return resource_records[:MAX_RESOURCE_LOOKUP_RESULTS]

    def _resource_record_rank(self, resource_record: dict[str, Any], query_text: str) -> tuple[int, str]:
        """Return a stable ranking key for resource search results."""

        resource_id = _coerce_positive_autotask_id(resource_record.get("id")) or 0
        first_name = _safe_optional_resource_text(resource_record.get("firstName"))
        last_name = _safe_optional_resource_text(resource_record.get("lastName"))
        resource_name = _resource_display_name(first_name, last_name, resource_id)
        normalized_query = _resource_match_text(query_text)
        normalized_candidates = [
            _resource_match_text(resource_name),
            _resource_match_text(f"{first_name or ''} {last_name or ''}"),
            _resource_match_text(f"{last_name or ''} {first_name or ''}"),
            _resource_match_text(resource_record.get("email")),
        ]
        if normalized_query in normalized_candidates:
            match_rank = 0
        elif any(candidate.startswith(normalized_query) for candidate in normalized_candidates):
            match_rank = 1
        elif any(normalized_query in candidate for candidate in normalized_candidates):
            match_rank = 2
        else:
            match_rank = 3

        return (match_rank, resource_name.casefold())

    def _query_tickets_for_company(self, client: httpx.Client, company_id: int) -> list[dict[str, Any]]:
        """Return a small server-filtered page of open Autotask tickets for one company ID."""

        ticket_filters: list[dict[str, Any]] = [
            {"op": "eq", "field": "companyID", "value": company_id},
            {"op": "notExist", "field": "completedDate"},
        ]
        if self.application_settings.autotask_status_complete_id is not None:
            ticket_filters.append(
                {
                    "op": "noteq",
                    "field": "status",
                    "value": self.application_settings.autotask_status_complete_id,
                }
            )

        query_payload = {
            "IncludeFields": ["id", "ticketNumber", "title", "description", "status", "completedDate", "source"],
            "filter": ticket_filters,
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/Tickets/query",
            query_payload=query_payload,
            action_description="Autotask ticket lookup",
            max_records=MAX_OPEN_TICKET_QUERY_RECORDS,
            follow_pagination=False,
        )

    def _is_open_ticket(self, ticket: dict[str, Any], status_labels: dict[int, str]) -> bool:
        """Return whether a ticket should be offered as an open-ticket match."""

        if ticket.get("completedDate"):
            return False

        raw_status_id = ticket.get("status")
        try:
            status_id = int(raw_status_id)
        except (TypeError, ValueError):
            status_id = None

        if self.application_settings.autotask_status_complete_id is not None and status_id == self.application_settings.autotask_status_complete_id:
            return False

        status_label = status_labels.get(status_id or -1, "")
        return status_label.strip().casefold() != "complete"

    def _build_ticket_options_for_company(
        self,
        client: httpx.Client,
        *,
        company_id: int,
        company_name: str,
        status_labels: dict[int, str],
        source_labels: dict[int, str],
    ) -> list[AutotaskTicketOption]:
        """Return safe open-ticket options for one Autotask company."""

        ticket_options: list[AutotaskTicketOption] = []
        for ticket in self._query_tickets_for_company(client, company_id):
            if not self._is_open_ticket(ticket, status_labels):
                continue

            ticket_number = str(ticket.get("ticketNumber") or "").strip()
            if not ticket_number:
                continue

            raw_status_id = ticket.get("status")
            try:
                status_id = int(raw_status_id)
            except (TypeError, ValueError):
                status_id = -1

            ticket_title = str(ticket.get("title") or "Untitled ticket")[:240]
            ticket_description = str(ticket.get("description") or "").strip()[:8000] or None
            detected_work_location = detect_work_location_from_text_or_ticket_source(
                "\n".join(text for text in (ticket_title, ticket_description) if text),
                _ticket_source_label(ticket, source_labels),
            )
            ticket_options.append(
                AutotaskTicketOption(
                    ticket_number=ticket_number,
                    title=ticket_title,
                    description=ticket_description,
                    status_label=status_labels.get(status_id, str(raw_status_id or "Unknown")),
                    company_name=company_name,
                    detected_work_location=detected_work_location,
                    work_location_label=work_location_label_for_detection(detected_work_location),
                    status_id=status_id if status_id >= 0 else None,
                )
            )

        return ticket_options

    def _query_ticket_notes_for_ticket_id(self, client: httpx.Client, ticket_id: int) -> list[dict[str, Any]]:
        """Return a bounded set of read-only TicketNotes rows for one ticket."""

        query_payload = {
            "IncludeFields": [
                "id",
                "ticketID",
                "title",
                "description",
                "createDateTime",
                "lastActivityDate",
                "createdByContactID",
                "creatorResourceID",
                "noteType",
                "publish",
            ],
            "filter": [{"op": "eq", "field": "ticketID", "value": ticket_id}],
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/TicketNotes/query",
            query_payload=query_payload,
            action_description="Autotask ticket note lookup",
            max_records=MAX_TICKET_NOTE_LOOKUP_RESULTS,
            follow_pagination=False,
        )

    def _query_ticket_note_contact_names_by_id(self, client: httpx.Client, contact_ids: list[int]) -> dict[int, str]:
        """Return bounded contact display names keyed by Autotask contact ID."""

        contact_names: dict[int, str] = {}
        for contact_id_chunk in _chunked_autotask_ids(contact_ids):
            if not contact_id_chunk:
                continue
            query_payload = {
                "IncludeFields": ["id", "firstName", "lastName"],
                "filter": [
                    {
                        "op": "in",
                        "field": "id",
                        "value": contact_id_chunk,
                    }
                ],
            }
            contact_records = self._query_paginated_items(
                client,
                endpoint_path="/Contacts/query",
                query_payload=query_payload,
                action_description="Autotask ticket note contact author lookup",
                max_records=len(contact_id_chunk),
                follow_pagination=False,
            )
            for contact_record in contact_records:
                contact_id = _coerce_positive_autotask_id(contact_record.get("id"))
                if contact_id is None:
                    continue
                first_name = _safe_optional_ticket_note_text(contact_record.get("firstName"), MAX_TICKET_NOTE_AUTHOR_LENGTH)
                last_name = _safe_optional_ticket_note_text(contact_record.get("lastName"), MAX_TICKET_NOTE_AUTHOR_LENGTH)
                contact_names[contact_id] = _contact_display_name(first_name, last_name, contact_id)

        return contact_names

    def _query_resource_names_by_id(
        self,
        client: httpx.Client,
        resource_ids: list[int],
        *,
        action_description: str,
    ) -> dict[int, str]:
        """Return bounded resource display names keyed by Autotask resource ID."""

        resource_names: dict[int, str] = {}
        for resource_id_chunk in _chunked_autotask_ids(resource_ids):
            if not resource_id_chunk:
                continue
            query_payload = {
                "IncludeFields": ["id", "firstName", "lastName"],
                "filter": [
                    {
                        "op": "in",
                        "field": "id",
                        "value": resource_id_chunk,
                    }
                ],
            }
            resource_records = self._query_paginated_items(
                client,
                endpoint_path="/Resources/query",
                query_payload=query_payload,
                action_description=action_description,
                max_records=len(resource_id_chunk),
                follow_pagination=False,
            )
            for resource_record in resource_records:
                resource_id = _coerce_positive_autotask_id(resource_record.get("id"))
                if resource_id is None:
                    continue
                first_name = _safe_optional_ticket_note_text(resource_record.get("firstName"), MAX_TICKET_NOTE_AUTHOR_LENGTH)
                last_name = _safe_optional_ticket_note_text(resource_record.get("lastName"), MAX_TICKET_NOTE_AUTHOR_LENGTH)
                resource_names[resource_id] = _resource_display_name(first_name, last_name, resource_id)

        return resource_names

    def _query_ticket_note_resource_names_by_id(self, client: httpx.Client, resource_ids: list[int]) -> dict[int, str]:
        """Return bounded resource display names for TicketNotes author IDs."""

        return self._query_resource_names_by_id(
            client,
            resource_ids,
            action_description="Autotask ticket note resource author lookup",
        )

    def _query_ticket_note_author_names(self, client: httpx.Client, note_records: list[dict[str, Any]]) -> dict[tuple[str, int], str]:
        """Return safe display names for TicketNotes author IDs."""

        author_names: dict[tuple[str, int], str] = {}
        contact_ids: list[int] = []
        resource_ids: list[int] = []
        for note_record in note_records:
            author_key = _ticket_note_author_key(note_record)
            if author_key is None:
                continue
            author_kind, author_id = author_key
            if author_kind == "contact":
                contact_ids.append(author_id)
            elif author_kind == "resource":
                resource_ids.append(author_id)

        try:
            contact_names = self._query_ticket_note_contact_names_by_id(client, sorted(set(contact_ids)))
        except AutotaskSubmissionError:
            contact_names = {}
        for contact_id in contact_ids:
            author_names[("contact", contact_id)] = contact_names.get(contact_id, f"Contact {contact_id}")

        try:
            resource_names = self._query_ticket_note_resource_names_by_id(client, sorted(set(resource_ids)))
        except AutotaskSubmissionError:
            resource_names = {}
        for resource_id in resource_ids:
            author_names[("resource", resource_id)] = resource_names.get(resource_id, f"Resource {resource_id}")

        return author_names

    def _build_ticket_notes_for_ticket_id(self, client: httpx.Client, ticket_id: int) -> list[AutotaskTicketNote]:
        """Return safe note view models for one selected Autotask ticket."""

        ticket_notes: list[AutotaskTicketNote] = []
        note_records = self._query_ticket_notes_for_ticket_id(client, ticket_id)
        author_names = self._query_ticket_note_author_names(client, note_records)
        for note_record in note_records:
            note_id = _coerce_positive_autotask_id(note_record.get("id"))
            if note_id is None:
                continue

            note_title = _safe_optional_ticket_note_text(
                note_record.get("title"),
                MAX_TICKET_NOTE_TITLE_LENGTH,
            ) or f"Ticket note {note_id}"
            note_description = _safe_optional_ticket_note_text(
                note_record.get("description"),
                MAX_TICKET_NOTE_BODY_LENGTH,
            )
            raw_publish = note_record.get("publish")
            try:
                publish = int(raw_publish) if raw_publish is not None else None
            except (TypeError, ValueError):
                publish = None
            author_key = _ticket_note_author_key(note_record)
            ticket_notes.append(
                AutotaskTicketNote(
                    note_id=note_id,
                    title=note_title,
                    description=note_description,
                    created_by=author_names.get(author_key) or _ticket_note_author_fallback(author_key),
                    created_at_utc=_parse_autotask_datetime(note_record.get("createDateTime")),
                    updated_at_utc=_parse_autotask_datetime(note_record.get("lastActivityDate")),
                    note_type=_safe_optional_ticket_note_text(note_record.get("noteType"), 80),
                    publish=publish,
                )
            )

        return sorted(
            ticket_notes,
            key=lambda note: note.created_at_utc or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def _query_ticket_time_entries_for_ticket_id(self, client: httpx.Client, ticket_id: int) -> list[dict[str, Any]]:
        """Return a bounded set of read-only TimeEntries rows for one ticket."""

        query_payload = {
            "IncludeFields": [
                "id",
                "ticketID",
                "resourceID",
                "startDateTime",
                "endDateTime",
                "hoursWorked",
                "summaryNotes",
            ],
            "filter": [{"op": "eq", "field": "ticketID", "value": ticket_id}],
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/TimeEntries/query",
            query_payload=query_payload,
            action_description="Autotask ticket time-entry lookup",
            max_records=MAX_TICKET_TIME_ENTRY_LOOKUP_RESULTS,
            follow_pagination=False,
        )

    def _query_ticket_time_entry_resource_names(
        self,
        client: httpx.Client,
        time_entry_records: list[dict[str, Any]],
    ) -> dict[int, str]:
        """Return safe resource names for TimeEntries.resourceID values."""

        resource_ids = sorted(
            {
                resource_id
                for time_entry_record in time_entry_records
                if (resource_id := _coerce_positive_autotask_id(time_entry_record.get("resourceID"))) is not None
            }
        )
        try:
            return self._query_resource_names_by_id(
                client,
                resource_ids,
                action_description="Autotask ticket time-entry resource lookup",
            )
        except AutotaskSubmissionError:
            return {}

    def _build_ticket_time_entries_for_ticket_id(
        self,
        client: httpx.Client,
        ticket_id: int,
    ) -> list[AutotaskTicketTimeEntry]:
        """Return safe time-entry view models for one selected Autotask ticket."""

        time_entries: list[AutotaskTicketTimeEntry] = []
        time_entry_records = self._query_ticket_time_entries_for_ticket_id(client, ticket_id)
        resource_names = self._query_ticket_time_entry_resource_names(client, time_entry_records)
        for time_entry_record in time_entry_records:
            time_entry_id = _coerce_positive_autotask_id(time_entry_record.get("id"))
            if time_entry_id is None:
                continue

            resource_id = _coerce_positive_autotask_id(time_entry_record.get("resourceID"))
            resource_name = resource_names.get(resource_id or 0)
            if not resource_name:
                resource_name = f"Resource {resource_id}" if resource_id is not None else "Unknown resource"

            time_entries.append(
                AutotaskTicketTimeEntry(
                    time_entry_id=time_entry_id,
                    resource_name=resource_name,
                    start_at_utc=_parse_autotask_datetime(time_entry_record.get("startDateTime")),
                    end_at_utc=_parse_autotask_datetime(time_entry_record.get("endDateTime")),
                    hours_worked=_coerce_time_entry_hours(time_entry_record.get("hoursWorked")),
                    summary_notes=_safe_optional_ticket_time_entry_text(
                        time_entry_record.get("summaryNotes"),
                        MAX_TICKET_TIME_ENTRY_SUMMARY_LENGTH,
                    ),
                )
            )

        return sorted(
            time_entries,
            key=lambda time_entry: time_entry.start_at_utc or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def list_open_tickets_for_client(
        self,
        client_name: str,
        autotask_company_id: int | None = None,
        *,
        resource_id: int | None = None,
    ) -> list[AutotaskTicketOption]:
        """Return open Autotask tickets for a selected company or client-name match."""

        safe_client_name = client_name.strip()
        if not safe_client_name:
            raise AutotaskSubmissionError("Client name is required before searching Autotask tickets.")

        cache_key = self._open_ticket_selection_cache_key(safe_client_name, autotask_company_id)
        cached_ticket_options = _get_cached_value(_OPEN_TICKET_SELECTION_CACHE, cache_key)
        if isinstance(cached_ticket_options, list) and cached_ticket_options:
            return cached_ticket_options[:MAX_TICKET_LOOKUP_RESULTS]

        ticket_options: list[AutotaskTicketOption] = []
        with self._client() as client:
            status_labels = self._query_ticket_status_labels(client)
            source_labels = self._query_ticket_source_labels_without_blocking_lookup(client)
            companies: list[dict[str, Any]]
            if autotask_company_id is not None:
                selected_company = self._query_company_by_id(
                    client,
                    autotask_company_id,
                )
                companies = [selected_company] if selected_company is not None else []
            else:
                companies = self._query_companies_by_name(
                    client,
                    safe_client_name,
                )

            for company in companies:
                if len(ticket_options) >= MAX_TICKET_LOOKUP_RESULTS:
                    break

                company_id = int(company["id"])
                company_name = str(company.get("companyName") or safe_client_name)
                ticket_options.extend(
                    self._build_ticket_options_for_company(
                        client,
                        company_id=company_id,
                        company_name=company_name,
                        status_labels=status_labels,
                        source_labels=source_labels,
                    )
                )

        selected_ticket_options = ticket_options[:MAX_TICKET_LOOKUP_RESULTS]
        if selected_ticket_options:
            _set_cached_value(
                _OPEN_TICKET_SELECTION_CACHE,
                cache_key,
                selected_ticket_options,
                OPEN_TICKET_SELECTION_CACHE_TTL_SECONDS,
            )

        return selected_ticket_options

    def list_ticket_notes(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketNote]:
        """Return safe read-only TicketNotes rows for one selected ticket number."""

        safe_ticket_number = ticket_number.strip().upper()
        if not safe_ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before searching Autotask ticket notes.")

        with self._client() as client:
            ticket_id = self._query_ticket_id(client, safe_ticket_number)
            return self._build_ticket_notes_for_ticket_id(client, ticket_id)[:MAX_TICKET_NOTE_LOOKUP_RESULTS]

    def list_ticket_time_entries(self, ticket_number: str, *, resource_id: int | None = None) -> list[AutotaskTicketTimeEntry]:
        """Return safe read-only TimeEntries rows for one selected ticket number."""

        safe_ticket_number = ticket_number.strip().upper()
        if not safe_ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before searching Autotask time entries.")

        with self._client() as client:
            ticket_id = self._query_ticket_id(client, safe_ticket_number)
            return self._build_ticket_time_entries_for_ticket_id(client, ticket_id)[:MAX_TICKET_TIME_ENTRY_LOOKUP_RESULTS]

    def search_companies(self, query_text: str, *, resource_id: int | None = None) -> list[AutotaskCompanyOption]:
        """Return active Autotask companies matching a user-entered query."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_COMPANY_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 3 characters before searching Autotask companies.")

        with self._client() as client:
            companies = self._query_companies_by_name(
                client,
                safe_query_text,
            )

        return [
            AutotaskCompanyOption(
                company_id=int(company["id"]),
                company_name=str(company.get("companyName") or "Unnamed company")[:120],
            )
            for company in companies
        ]

    def get_company_by_id(self, company_id: int, *, resource_id: int | None = None) -> AutotaskCompanyOption | None:
        """Return one active Autotask company by selected ID for server validation."""

        with self._client() as client:
            company = self._query_company_by_id(client, company_id)
        if company is None:
            return None
        return AutotaskCompanyOption(
            company_id=int(company["id"]),
            company_name=str(company.get("companyName") or "Unnamed company")[:120],
        )

    def search_resources(self, query_text: str) -> list[AutotaskResourceOption]:
        """Return likely Autotask resources for a managed web-user name."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_RESOURCE_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 2 characters before searching Autotask resources.")

        with self._client() as client:
            resource_records = self._query_resources_by_name(client, safe_query_text)

        resource_options: list[AutotaskResourceOption] = []
        for resource_record in resource_records:
            resource_id = _coerce_positive_autotask_id(resource_record.get("id"))
            if resource_id is None:
                continue

            first_name = _safe_optional_resource_text(resource_record.get("firstName"))
            last_name = _safe_optional_resource_text(resource_record.get("lastName"))
            resource_options.append(
                AutotaskResourceOption(
                    resource_id=resource_id,
                    resource_name=_resource_display_name(first_name, last_name, resource_id),
                    first_name=first_name,
                    last_name=last_name,
                    email=_safe_optional_resource_text(resource_record.get("email")),
                )
            )

        return resource_options[:MAX_RESOURCE_LOOKUP_RESULTS]

    def list_resource_service_desk_roles(self, resource_id: int) -> list[AutotaskServiceDeskRoleOption]:
        """Return active service-desk roles for a managed user's Autotask resource."""

        if resource_id <= 0:
            raise AutotaskSubmissionError("Autotask resource ID must be a positive number.")

        with self._client() as client:
            role_records = self._query_active_resource_service_desk_role_records(client, resource_id)
            active_role_ids = [
                role_id
                for role_record in role_records
                if (role_id := _coerce_positive_autotask_id(role_record.get("roleID"))) is not None
            ]
            try:
                role_names_by_id = self._query_role_names_by_id(client, active_role_ids)
            except AutotaskSubmissionError:
                role_names_by_id = {}

        role_options_by_id: dict[int, AutotaskServiceDeskRoleOption] = {}
        for role_record in role_records:
            role_id = _coerce_positive_autotask_id(role_record.get("roleID"))
            if role_id is None:
                continue
            is_default = _is_autotask_truthy(role_record.get("isDefault"))
            role_name = role_names_by_id.get(role_id)
            existing_option = role_options_by_id.get(role_id)
            if existing_option is not None and not is_default:
                continue
            role_options_by_id[role_id] = AutotaskServiceDeskRoleOption(
                role_id=role_id,
                name=role_name,
                label=_service_desk_role_label(role_id, role_name=role_name, is_default=is_default),
                is_default=is_default,
            )

        return sorted(role_options_by_id.values(), key=lambda option: (not option.is_default, option.role_id))

    def list_todays_service_calls_for_resource(
        self,
        resource_id: int,
        current_time_utc: datetime | None = None,
        local_service_date: date | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return service calls assigned to one managed user's resource for a local date."""

        if resource_id <= 0:
            raise AutotaskSubmissionError("A managed web user's Autotask resource ID is required before loading today's service calls.")

        safe_current_time_utc = ensure_utc(current_time_utc or now_utc())
        selected_local_date = local_service_date or local_date_for(safe_current_time_utc)
        local_day_start_utc, local_day_end_utc = local_day_bounds_utc(selected_local_date)
        cache_key = self._service_call_selection_cache_key(resource_id, local_day_start_utc, local_day_end_utc)
        cached_service_call_options = _get_cached_value(_SERVICE_CALL_SELECTION_CACHE, cache_key)
        if isinstance(cached_service_call_options, list):
            return cached_service_call_options[:MAX_SERVICE_CALL_LOOKUP_RESULTS]

        with self._client() as client:
            service_call_records = self._query_todays_service_calls(
                client,
                local_day_start_utc=local_day_start_utc,
                local_day_end_utc=local_day_end_utc,
            )
            service_call_ids = [
                service_call_id
                for service_call_record in service_call_records
                if (service_call_id := _coerce_positive_autotask_id(service_call_record.get("id"))) is not None
            ]
            if not service_call_ids:
                _set_cached_value(
                    _SERVICE_CALL_SELECTION_CACHE,
                    cache_key,
                    [],
                    SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS,
                )
                return []

            service_call_ticket_records = self._query_service_call_tickets_for_service_calls(client, service_call_ids)
            service_call_ticket_ids = [
                service_call_ticket_id
                for service_call_ticket_record in service_call_ticket_records
                if (service_call_ticket_id := _coerce_positive_autotask_id(service_call_ticket_record.get("id"))) is not None
            ]
            if not service_call_ticket_ids:
                _set_cached_value(
                    _SERVICE_CALL_SELECTION_CACHE,
                    cache_key,
                    [],
                    SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS,
                )
                return []

            service_call_ticket_resource_records = self._query_service_call_ticket_resources(
                client,
                resource_id=resource_id,
                service_call_ticket_ids=service_call_ticket_ids,
            )
            assigned_service_call_ticket_ids = {
                service_call_ticket_id
                for resource_record in service_call_ticket_resource_records
                if (service_call_ticket_id := _coerce_positive_autotask_id(resource_record.get("serviceCallTicketID"))) is not None
            }
            assigned_ticket_ids = [
                ticket_id
                for service_call_ticket_record in service_call_ticket_records
                if _coerce_positive_autotask_id(service_call_ticket_record.get("id")) in assigned_service_call_ticket_ids
                if (ticket_id := _coerce_positive_autotask_id(service_call_ticket_record.get("ticketID"))) is not None
            ]
            if not assigned_ticket_ids:
                _set_cached_value(
                    _SERVICE_CALL_SELECTION_CACHE,
                    cache_key,
                    [],
                    SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS,
                )
                return []

            ticket_records_by_id = self._query_tickets_by_ids(client, assigned_ticket_ids)
            company_ids = [
                company_id
                for service_call_record in service_call_records
                if (company_id := _coerce_positive_autotask_id(service_call_record.get("companyID"))) is not None
            ]
            company_ids.extend(
                company_id
                for ticket_record in ticket_records_by_id.values()
                if (company_id := _coerce_positive_autotask_id(ticket_record.get("companyID"))) is not None
            )
            company_records_by_id = self._query_companies_by_ids(
                client,
                company_ids,
            )
            status_labels = self._query_ticket_status_labels(client)
            source_labels = self._query_ticket_source_labels_without_blocking_lookup(client)
            service_call_options = self._build_service_call_options(
                service_call_records=service_call_records,
                service_call_ticket_records=service_call_ticket_records,
                service_call_ticket_resource_records=service_call_ticket_resource_records,
                ticket_records_by_id=ticket_records_by_id,
                company_records_by_id=company_records_by_id,
                status_labels=status_labels,
                source_labels=source_labels,
            )[:MAX_SERVICE_CALL_LOOKUP_RESULTS]

        _set_cached_value(
            _SERVICE_CALL_SELECTION_CACHE,
            cache_key,
            service_call_options,
            SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS,
        )
        return service_call_options

    def _query_resource_service_desk_role(
        self,
        client: httpx.Client,
        resource_id: int,
        *,
        source_prefix: str,
    ) -> _ServiceDeskRoleLookup | None:
        """Return an unambiguous active service-desk role for an Autotask resource."""

        role_records = self._query_active_resource_service_desk_role_records(client, resource_id)
        active_role_ids: list[int] = []
        for role_record in role_records:
            role_id = _coerce_positive_autotask_id(role_record.get("roleID"))
            if role_id is None:
                continue
            active_role_ids.append(role_id)
            if _is_autotask_truthy(role_record.get("isDefault")):
                return _ServiceDeskRoleLookup(
                    role_id=role_id,
                    source=f"{source_prefix}.default.roleID",
                )

        unique_active_role_ids = list(dict.fromkeys(active_role_ids))
        if len(unique_active_role_ids) == 1:
            return _ServiceDeskRoleLookup(
                role_id=unique_active_role_ids[0],
                source=f"{source_prefix}.singleActive.roleID",
            )

        return None

    def _query_active_resource_service_desk_role_records(
        self,
        client: httpx.Client,
        resource_id: int,
    ) -> list[dict[str, Any]]:
        """Return active ResourceServiceDeskRoles records for one resource."""

        query_payload = {
            "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
            "filter": [
                {"op": "eq", "field": "resourceID", "value": resource_id},
                {"op": "eq", "field": "isActive", "value": True},
            ],
        }
        return self._query_paginated_items(
            client,
            endpoint_path="/ResourceServiceDeskRoles/query",
            query_payload=query_payload,
            action_description="Autotask resource service-desk role lookup",
            max_records=50,
            follow_pagination=False,
        )

    def _query_role_names_by_id(
        self,
        client: httpx.Client,
        role_ids: list[int],
    ) -> dict[int, str]:
        """Return Autotask role names keyed by role ID for dropdown labels."""

        role_names_by_id: dict[int, str] = {}
        for role_id_chunk in _chunked_autotask_ids(role_ids):
            if not role_id_chunk:
                continue
            query_payload = {
                "IncludeFields": ["id", "name", "isActive"],
                "filter": [
                    {
                        "op": "in",
                        "field": "id",
                        "value": role_id_chunk,
                    }
                ],
            }
            role_records = self._query_paginated_items(
                client,
                endpoint_path="/Roles/query",
                query_payload=query_payload,
                action_description="Autotask service-desk role name lookup",
                max_records=len(role_id_chunk),
                follow_pagination=False,
            )
            for role_record in role_records:
                role_id = _coerce_positive_autotask_id(role_record.get("id"))
                role_name = _safe_optional_resource_text(
                    role_record.get("name"),
                    max_length=MAX_SERVICE_DESK_ROLE_NAME_LENGTH,
                )
                if role_id is not None and role_name:
                    role_names_by_id[role_id] = role_name

        return role_names_by_id

    def _query_ticket_secondary_resource_role(
        self,
        client: httpx.Client,
        ticket_id: int,
        resource_id: int,
    ) -> _ServiceDeskRoleLookup | None:
        """Return the ticket-specific secondary-resource role for a resource."""

        query_payload = {
            "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
            "filter": [
                {"op": "eq", "field": "ticketID", "value": ticket_id},
                {"op": "eq", "field": "resourceID", "value": resource_id},
            ],
        }
        secondary_resource_records = self._query_paginated_items(
            client,
            endpoint_path="/TicketSecondaryResources/query",
            query_payload=query_payload,
            action_description="Autotask ticket secondary resource role lookup",
            max_records=50,
            follow_pagination=False,
        )

        role_ids = [
            role_id
            for secondary_resource_record in secondary_resource_records
            if (role_id := _coerce_positive_autotask_id(secondary_resource_record.get("roleID"))) is not None
        ]
        unique_role_ids = list(dict.fromkeys(role_ids))
        if len(unique_role_ids) == 1:
            return _ServiceDeskRoleLookup(
                role_id=unique_role_ids[0],
                source="ticket.secondaryResource.roleID",
            )

        return None

    def _query_ticket_time_entry_context(
        self,
        client: httpx.Client,
        ticket_number: str,
        *,
        resource_id: int,
        default_service_desk_role_id: int | None = None,
    ) -> AutotaskTicketTimeEntryContext:
        """Find ticket fields needed for a matching ticket TimeEntries create."""

        query_payload = {
            "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
            "filter": [{"op": "eq", "field": "ticketNumber", "value": ticket_number}],
        }
        tickets = self._query_paginated_items(
            client,
            endpoint_path="/Tickets/query",
            query_payload=query_payload,
            action_description="Autotask ticket number lookup",
            max_records=1,
            follow_pagination=False,
        )
        if not tickets:
            raise AutotaskSubmissionError(f"No Autotask ticket found for ticket number {ticket_number}.")

        ticket_id = tickets[0].get("id")
        if ticket_id is None:
            raise AutotaskSubmissionError("Autotask ticket query did not return an ID.")

        safe_ticket_id = _coerce_positive_autotask_id(ticket_id)
        if safe_ticket_id is None:
            raise AutotaskSubmissionError("Autotask ticket query returned an invalid ticket ID.")

        raw_role_id = tickets[0].get("assignedResourceroleID")
        if raw_role_id in (None, ""):
            raw_role_id = tickets[0].get("assignedResourceRoleID")
        role_id = _coerce_positive_autotask_id(raw_role_id)
        role_id_source = "ticket.assignedResourceroleID"
        assigned_resource_id = _coerce_positive_autotask_id(tickets[0].get("assignedResourceID"))
        if assigned_resource_id is None:
            assigned_resource_id = _coerce_positive_autotask_id(tickets[0].get("assignedresourceID"))
        if role_id is None:
            secondary_role_lookup = self._query_ticket_secondary_resource_role(client, safe_ticket_id, resource_id)
            if secondary_role_lookup is not None:
                role_id = secondary_role_lookup.role_id
                role_id_source = secondary_role_lookup.source

        if role_id is None:
            role_lookup_candidates = [
                (assigned_resource_id, "ticket.assignedResourceID.ResourceServiceDeskRoles"),
            ]
            checked_resource_ids: set[int] = set()
            for role_resource_id, source_prefix in role_lookup_candidates:
                if role_resource_id is None or role_resource_id in checked_resource_ids:
                    continue
                checked_resource_ids.add(role_resource_id)
                role_lookup = self._query_resource_service_desk_role(
                    client,
                    role_resource_id,
                    source_prefix=source_prefix,
                )
                if role_lookup is not None:
                    role_id = role_lookup.role_id
                    role_id_source = role_lookup.source
                    break

        if role_id is None and default_service_desk_role_id is not None:
            role_id = default_service_desk_role_id
            role_id_source = "managed_web_user.autotask_default_service_desk_role_id"

        if role_id is None:
            role_lookup = self._query_resource_service_desk_role(
                client,
                resource_id,
                source_prefix="managed_web_user.autotask_resource_id.ResourceServiceDeskRoles",
            )
            if role_lookup is not None:
                role_id = role_lookup.role_id
                role_id_source = role_lookup.source

            if role_id is None:
                raise AutotaskSubmissionError(
                    f"Autotask ticket {ticket_number} did not return assignedResourceroleID, "
                    "the submitting resource was not found with an unambiguous TicketSecondaryResources role, "
                    "the ticket assigned resource did not return an unambiguous active ResourceServiceDeskRoles role, "
                    "no configured default service-desk role was available for the submitting user, and the submitting "
                    "resource did not return an unambiguous active ResourceServiceDeskRoles role for time entry creation."
                )

        return AutotaskTicketTimeEntryContext(
            ticket_id=safe_ticket_id,
            role_id=role_id,
            role_id_source=role_id_source,
            assigned_resource_id=assigned_resource_id,
            billing_code_id=_coerce_positive_autotask_id(tickets[0].get("billingCodeID")),
        )

    def _query_ticket_id(self, client: httpx.Client, ticket_number: str) -> int:
        """Find the Autotask ticket ID for status updates."""

        query_payload = {
            "IncludeFields": ["id", "ticketNumber"],
            "filter": [{"op": "eq", "field": "ticketNumber", "value": ticket_number}],
        }
        tickets = self._query_paginated_items(
            client,
            endpoint_path="/Tickets/query",
            query_payload=query_payload,
            action_description="Autotask ticket number lookup",
            max_records=1,
            follow_pagination=False,
        )
        if not tickets:
            raise AutotaskSubmissionError(f"No Autotask ticket found for ticket number {ticket_number}.")

        ticket_id = _coerce_positive_autotask_id(tickets[0].get("id"))
        if ticket_id is None:
            raise AutotaskSubmissionError("Autotask ticket query did not return a valid ID.")

        return ticket_id

    def _ticket_status_id(self, ticket_status: TicketStatus | None, *, required: bool = False) -> int | None:
        """Return the configured Autotask picklist ID for one local ticket status."""

        if ticket_status is None:
            if required:
                raise AutotaskSubmissionError("Ticket status is required before Autotask submission.")
            return None

        status_id = self.application_settings.autotask_status_id_map.get(ticket_status.value)
        if status_id is None and required:
            raise AutotaskSubmissionError(
                f"Autotask status ID for {TICKET_STATUS_DISPLAY_LABELS[ticket_status]} is not configured."
            )

        return status_id

    def _update_ticket_status(
        self,
        client: httpx.Client,
        ticket_id: int,
        ticket_status: TicketStatus | None,
        *,
        required: bool = False,
    ) -> None:
        """Update the Autotask ticket status when a tenant picklist ID is configured."""

        status_id = self._ticket_status_id(ticket_status, required=required)
        if status_id is None:
            return

        response = self._api_request(
            client,
            "PATCH",
            "/Tickets",
            "Autotask ticket status update",
            json={"id": ticket_id, "status": status_id},
        )
        self._raise_for_safe_response(response, "Autotask ticket status update")

    def _time_entry_payload(
        self,
        job: Job,
        *,
        ticket_id: int | None = None,
        resource_id: int | None = None,
        role_id: int | None = None,
    ) -> dict[str, Any]:
        """Build the editable TimeEntries fields shared by create and update."""

        if job.rounded_end_utc is None:
            raise AutotaskSubmissionError("Job has no rounded end time.")

        payload: dict[str, Any] = {
            "startDateTime": format_autotask_datetime(job.rounded_start_utc),
            "endDateTime": format_autotask_datetime(job.rounded_end_utc),
            "hoursWorked": float(_job_duration_hours(job)),
            "summaryNotes": build_autotask_summary_notes(job),
            "appendToResolution": _append_to_resolution_for_job(job),
        }
        if ticket_id is not None:
            if resource_id is None or resource_id <= 0:
                raise AutotaskSubmissionError("A managed web user's Autotask resource ID is required before Autotask submission.")
            if role_id is None or role_id <= 0:
                raise AutotaskSubmissionError("An Autotask role ID is required before submission.")
            payload.update(
                {
                    "ticketID": ticket_id,
                    "resourceID": resource_id,
                    "roleID": role_id,
                    "timeEntryType": self.application_settings.autotask_time_entry_type,
                }
            )

        return payload

    def _create_time_entry(
        self,
        client: httpx.Client,
        job: Job,
        ticket_id: int,
        *,
        resource_id: int,
        role_id: int,
    ) -> str:
        """Create the Autotask TimeEntries row for the accepted job."""

        payload = self._time_entry_payload(job, ticket_id=ticket_id, resource_id=resource_id, role_id=role_id)
        response = self._api_request(
            client,
            "POST",
            "/TimeEntries",
            "Autotask time entry creation",
            json=payload,
        )
        self._raise_for_safe_response(response, "Autotask time entry creation")
        response_payload = response.json()
        item_id = response_payload.get("itemId") or response_payload.get("id") or response_payload.get("ItemId")
        if item_id is None:
            return "created-without-id"

        return str(item_id)

    def _update_time_entry(self, client: httpx.Client, job: Job, external_id: str) -> None:
        """Patch editable fields on an existing Autotask TimeEntries row."""

        time_entry_id = _coerce_positive_autotask_id(external_id)
        if time_entry_id is None:
            raise AutotaskSubmissionError("Existing Autotask time entry ID is required before updating.")

        payload = self._time_entry_payload(job)
        payload["id"] = time_entry_id
        response = self._api_request(
            client,
            "PATCH",
            "/TimeEntries",
            "Autotask time entry update",
            json=payload,
        )
        self._raise_for_safe_response(response, "Autotask time entry update")

    def _delete_time_entry(self, client: httpx.Client, external_id: str) -> None:
        """Delete an existing Autotask TimeEntries row by remote ID."""

        time_entry_id = _coerce_positive_autotask_id(external_id)
        if time_entry_id is None:
            raise AutotaskSubmissionError("Existing Autotask time entry ID is required before deleting.")

        response = self._api_request(
            client,
            "DELETE",
            f"/TimeEntries/{time_entry_id}",
            "Autotask time entry deletion",
        )
        self._raise_for_safe_response(response, "Autotask time entry deletion")

    def _ticket_note_payload(self, job: Job, *, ticket_id: int | None = None) -> dict[str, Any]:
        """Build customer-visible TicketNotes fields shared by create and update."""

        note_title = str(job.note_title or "").strip()
        if not note_title:
            raise AutotaskSubmissionError("Ticket note title is required before Autotask submission.")

        note_description = build_ticket_note_description(job)
        if not note_description:
            raise AutotaskSubmissionError("Ticket note description is required before Autotask submission.")

        payload: dict[str, Any] = {
            "title": note_title[:MAX_TICKET_NOTE_TITLE_LENGTH],
            "description": note_description,
            "publish": CUSTOMER_VISIBLE_TICKET_NOTE_PUBLISH_VALUE,
            "noteType": DEFAULT_TICKET_NOTE_TYPE,
            "appendToResolution": _append_to_resolution_for_job(job),
        }
        if ticket_id is not None:
            payload["ticketID"] = ticket_id

        return payload

    def _create_ticket_note(self, client: httpx.Client, job: Job, ticket_id: int) -> str:
        """Create the customer-visible Autotask TicketNotes row for the accepted job."""

        payload = self._ticket_note_payload(job, ticket_id=ticket_id)
        response = self._api_request(
            client,
            "POST",
            "/TicketNotes",
            "Autotask ticket note creation",
            json=payload,
        )
        self._raise_for_safe_response(response, "Autotask ticket note creation")
        response_payload = response.json()
        item_id = response_payload.get("itemId") or response_payload.get("id") or response_payload.get("ItemId")
        if item_id is None:
            return "created-without-id"

        return str(item_id)

    def _update_ticket_note(self, client: httpx.Client, job: Job, external_id: str) -> None:
        """Patch editable fields on an existing Autotask TicketNotes row."""

        ticket_note_id = _coerce_positive_autotask_id(external_id)
        if ticket_note_id is None:
            raise AutotaskSubmissionError("Existing Autotask ticket note ID is required before updating.")

        payload = self._ticket_note_payload(job)
        payload["id"] = ticket_note_id
        response = self._api_request(
            client,
            "PATCH",
            "/TicketNotes",
            "Autotask ticket note update",
            json=payload,
        )
        self._raise_for_safe_response(response, "Autotask ticket note update")

    def _delete_ticket_note(self, client: httpx.Client, external_id: str) -> None:
        """Delete an existing Autotask TicketNotes row by remote ID."""

        ticket_note_id = _coerce_positive_autotask_id(external_id)
        if ticket_note_id is None:
            raise AutotaskSubmissionError("Existing Autotask ticket note ID is required before deleting.")

        response = self._api_request(
            client,
            "DELETE",
            f"/TicketNotes/{ticket_note_id}",
            "Autotask ticket note deletion",
        )
        self._raise_for_safe_response(response, "Autotask ticket note deletion")

    def _submit_ticket_note_job(self, job: Job, *, resource_id: int) -> AutotaskSubmissionResult:
        """Submit a reviewed job as a customer-visible Autotask ticket note."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask ticket note submission.")

        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "resourceID": resource_id,
                "resourceIDSource": "managed_web_user.autotask_resource_id",
                "ticketStatusUpdatePolicy": "required_on_submit",
                "ticketStatusUpdateAttempted": False,
                "ticketStatusPreUpdate": None,
                "ticketStatusPostUpdate": None,
            }
        )
        try:
            self._ticket_status_id(job.ticket_status, required=True)
            with self._client() as client:
                ticket_id = self._query_ticket_id(client, job.ticket_number)
                snapshot["ticketID"] = ticket_id
                snapshot["ticketStatusUpdateAttempted"] = True
                if job.ticket_status == TicketStatus.COMPLETE:
                    snapshot["ticketStatusPreUpdate"] = TicketStatus.IN_PROGRESS.value
                    self._update_ticket_status(client, ticket_id, TicketStatus.IN_PROGRESS, required=True)
                else:
                    snapshot["ticketStatusPreUpdate"] = job.ticket_status.value if job.ticket_status else None
                    self._update_ticket_status(client, ticket_id, job.ticket_status, required=True)
                external_id = self._create_ticket_note(client, job, ticket_id)
                if job.ticket_status == TicketStatus.COMPLETE:
                    snapshot["ticketStatusPostUpdate"] = TicketStatus.COMPLETE.value
                    self._update_ticket_status(client, ticket_id, TicketStatus.COMPLETE, required=True)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask ticket note submission failed.",
                operation="Autotask ticket note submission",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=None,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask ticket note submission")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def submit_job(
        self,
        job: Job,
        *,
        resource_id: int,
        default_service_desk_role_id: int | None = None,
    ) -> AutotaskSubmissionResult:
        """Submit a reviewed job to the Autotask REST API."""

        if job.entry_type == EntryType.TICKET_NOTE:
            return self._submit_ticket_note_job(job, resource_id=resource_id)

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask submission.")

        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "resourceID": resource_id,
                "resourceIDSource": "managed_web_user.autotask_resource_id",
                "configuredDefaultServiceDeskRoleID": default_service_desk_role_id,
                "roleIDSource": (
                    "ticket.assignedResourceroleID, ticket secondary resource role, "
                    "ticket.assignedResourceID ResourceServiceDeskRoles, configured managed user default role, "
                    "or managed user ResourceServiceDeskRoles"
                ),
                "billingCodeIDSource": "ticket inheritance",
                "timeEntryType": self.application_settings.autotask_time_entry_type,
                "ticketStatusUpdatePolicy": "required_on_submit",
                "ticketStatusUpdateAttempted": False,
                "ticketStatusPreUpdate": None,
                "ticketStatusPostUpdate": None,
            }
        )
        try:
            self._ticket_status_id(job.ticket_status, required=True)
            with self._client() as client:
                ticket_context = self._query_ticket_time_entry_context(
                    client,
                    job.ticket_number,
                    resource_id=resource_id,
                    default_service_desk_role_id=default_service_desk_role_id,
                )
                should_update_ticket_status = True
                snapshot["roleID"] = ticket_context.role_id
                snapshot["roleIDSource"] = ticket_context.role_id_source
                snapshot["ticketAssignedResourceID"] = ticket_context.assigned_resource_id
                snapshot["ticketBillingCodeID"] = ticket_context.billing_code_id
                snapshot["ticketStatusUpdateAttempted"] = should_update_ticket_status
                if should_update_ticket_status and job.ticket_status == TicketStatus.COMPLETE:
                    snapshot["ticketStatusPreUpdate"] = TicketStatus.IN_PROGRESS.value
                    self._update_ticket_status(client, ticket_context.ticket_id, TicketStatus.IN_PROGRESS, required=True)
                elif should_update_ticket_status:
                    snapshot["ticketStatusPreUpdate"] = job.ticket_status.value if job.ticket_status else None
                    self._update_ticket_status(client, ticket_context.ticket_id, job.ticket_status, required=True)
                external_id = self._create_time_entry(
                    client,
                    job,
                    ticket_context.ticket_id,
                    resource_id=resource_id,
                    role_id=ticket_context.role_id,
                )
                if should_update_ticket_status and job.ticket_status == TicketStatus.COMPLETE:
                    snapshot["ticketStatusPostUpdate"] = TicketStatus.COMPLETE.value
                    self._update_ticket_status(client, ticket_context.ticket_id, TicketStatus.COMPLETE, required=True)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask time entry submission failed.",
                operation="Autotask time entry submission",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=None,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask time entry submission")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_time_entry(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Update an existing Autotask time entry from reviewed submitted fields."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask time entry updates.")

        should_update_ticket_status = job.ticket_status is not None
        should_reopen_complete_ticket = should_update_ticket_status and previous_ticket_status == TicketStatus.COMPLETE
        should_update_status_after_time_entry = should_update_ticket_status and (
            (should_reopen_complete_ticket and job.ticket_status != TicketStatus.IN_PROGRESS)
            or job.ticket_status == TicketStatus.COMPLETE
        )
        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "operation": "update_time_entry",
                "external_id": external_id,
                "resourceID": resource_id,
                "resourceIDSource": "managed_web_user.autotask_resource_id",
                "previousTicketStatus": previous_ticket_status.value if previous_ticket_status else None,
                "ticketStatusUpdatePolicy": "required_on_edit",
                "ticketStatusUpdateRequested": should_update_ticket_status,
                "ticketStatusUpdateAttempted": should_update_ticket_status,
                "ticketStatusPreUpdate": TicketStatus.IN_PROGRESS.value if should_reopen_complete_ticket else None,
                "ticketStatusPostUpdate": (
                    job.ticket_status.value if should_update_status_after_time_entry and job.ticket_status is not None else None
                ),
            }
        )
        try:
            if should_update_ticket_status:
                self._ticket_status_id(job.ticket_status, required=True)
            if should_reopen_complete_ticket:
                self._ticket_status_id(TicketStatus.IN_PROGRESS, required=True)
            with self._client() as client:
                ticket_id: int | None = None
                if should_reopen_complete_ticket or should_update_ticket_status:
                    ticket_id = self._query_ticket_id(client, job.ticket_number)
                if should_reopen_complete_ticket and ticket_id is not None:
                    self._update_ticket_status(client, ticket_id, TicketStatus.IN_PROGRESS, required=True)
                elif should_update_ticket_status and job.ticket_status != TicketStatus.COMPLETE and ticket_id is not None:
                    self._update_ticket_status(client, ticket_id, job.ticket_status, required=True)
                self._update_time_entry(client, job, external_id)
                if should_update_status_after_time_entry and job.ticket_status is not None:
                    if ticket_id is None:
                        ticket_id = self._query_ticket_id(client, job.ticket_number)
                    self._update_ticket_status(client, ticket_id, job.ticket_status, required=True)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask time entry update failed.",
                operation="Autotask time entry update",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask time entry update")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_ticket_note(
        self,
        job: Job,
        external_id: str,
        *,
        resource_id: int,
        previous_ticket_status: TicketStatus | None = None,
    ) -> AutotaskSubmissionResult:
        """Update an existing Autotask ticket note from reviewed submitted fields."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask ticket note updates.")

        should_update_ticket_status = job.ticket_status is not None
        should_reopen_complete_ticket = should_update_ticket_status and previous_ticket_status == TicketStatus.COMPLETE
        should_update_status_after_note = should_update_ticket_status and (
            (should_reopen_complete_ticket and job.ticket_status != TicketStatus.IN_PROGRESS)
            or job.ticket_status == TicketStatus.COMPLETE
        )
        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "operation": "update_ticket_note",
                "external_id": external_id,
                "resourceID": resource_id,
                "resourceIDSource": "managed_web_user.autotask_resource_id",
                "previousTicketStatus": previous_ticket_status.value if previous_ticket_status else None,
                "ticketStatusUpdatePolicy": "required_on_edit",
                "ticketStatusUpdateRequested": should_update_ticket_status,
                "ticketStatusUpdateAttempted": should_update_ticket_status,
                "ticketStatusPreUpdate": TicketStatus.IN_PROGRESS.value if should_reopen_complete_ticket else None,
                "ticketStatusPostUpdate": (
                    job.ticket_status.value if should_update_status_after_note and job.ticket_status is not None else None
                ),
            }
        )
        try:
            if should_update_ticket_status:
                self._ticket_status_id(job.ticket_status, required=True)
            if should_reopen_complete_ticket:
                self._ticket_status_id(TicketStatus.IN_PROGRESS, required=True)
            with self._client() as client:
                ticket_id: int | None = None
                if should_reopen_complete_ticket or should_update_ticket_status:
                    ticket_id = self._query_ticket_id(client, job.ticket_number)
                    snapshot["ticketID"] = ticket_id
                if should_reopen_complete_ticket and ticket_id is not None:
                    self._update_ticket_status(client, ticket_id, TicketStatus.IN_PROGRESS, required=True)
                elif should_update_ticket_status and job.ticket_status != TicketStatus.COMPLETE and ticket_id is not None:
                    self._update_ticket_status(client, ticket_id, job.ticket_status, required=True)
                self._update_ticket_note(client, job, external_id)
                if should_update_status_after_note and job.ticket_status is not None:
                    if ticket_id is None:
                        ticket_id = self._query_ticket_id(client, job.ticket_number)
                        snapshot["ticketID"] = ticket_id
                    self._update_ticket_status(client, ticket_id, job.ticket_status, required=True)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask ticket note update failed.",
                operation="Autotask ticket note update",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask ticket note update")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_ticket_note(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Delete an existing Autotask ticket note from a submitted job."""

        snapshot = {
            "operation": "delete_ticket_note",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
            "resourceID": resource_id,
            "resourceIDSource": "managed_web_user.autotask_resource_id",
        }
        try:
            with self._client() as client:
                self._delete_ticket_note(client, external_id)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask ticket note deletion failed.",
                operation="Autotask ticket note deletion",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask ticket note deletion")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_time_entry(self, job: Job, external_id: str, *, resource_id: int) -> AutotaskSubmissionResult:
        """Delete an existing Autotask time entry from a submitted job."""

        snapshot = {
            "operation": "delete_time_entry",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
            "resourceID": resource_id,
            "resourceIDSource": "managed_web_user.autotask_resource_id",
        }
        try:
            with self._client() as client:
                self._delete_time_entry(client, external_id)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            record_autotask_api_failure(
                "Autotask time entry deletion failed.",
                operation="Autotask time entry deletion",
            )
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        record_autotask_api_success(operation="Autotask time entry deletion")
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )


def get_autotask_provider(application_settings: Settings = settings) -> BaseAutotaskProvider:
    """Return the configured Autotask provider."""

    if application_settings.autotask_provider == "mock":
        return MockAutotaskProvider()

    if application_settings.autotask_provider == "autotask":
        return LiveAutotaskProvider(application_settings)

    raise AutotaskSubmissionError(f"Unsupported Autotask provider: {application_settings.autotask_provider}")


def _run_autotask_connectivity_check(application_settings: Settings) -> AutotaskConnectivityResult:
    """Run the live provider connectivity check and normalize configuration errors."""

    try:
        provider = get_autotask_provider(application_settings)
        return provider.test_connectivity()
    except AutotaskSubmissionError as exc:
        return AutotaskConnectivityResult(
            provider=application_settings.autotask_provider,
            available=False,
            summary=f"Autotask provider is not ready: {exc}",
            tips=(
                "Set AUTOTASK_PROVIDER=autotask for production.",
                "Confirm AUTOTASK_BASE_URL, AUTOTASK_USERNAME, AUTOTASK_SECRET, and AUTOTASK_API_INTEGRATION_CODE are set in .env.",
                "Recreate the app container after changing .env so the new settings are loaded.",
            ),
            checked_operations=("provider configuration",),
        )


def test_autotask_connectivity(application_settings: Settings = settings) -> AutotaskConnectivityResult:
    """Return a fresh safe Autotask dependency result for diagnostics."""

    connectivity_result = _run_autotask_connectivity_check(application_settings)
    record_autotask_connectivity_result(
        available=connectivity_result.available,
        summary=connectivity_result.summary,
        operation=connectivity_result.failed_operation,
    )
    return connectivity_result
