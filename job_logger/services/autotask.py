"""Autotask time-entry submission providers."""

from __future__ import annotations

import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from threading import RLock
from typing import Any

import httpx

from job_logger.config import Settings, settings
from job_logger.enums import TicketStatus, WorkLocation
from job_logger.models import Job
from job_logger.time_utils import ensure_utc, format_autotask_datetime, local_date_for, local_day_bounds_utc, now_utc, rounded_duration_minutes

MAX_COMPANY_MATCHES_FOR_TICKET_LOOKUP = 10
MAX_TICKET_LOOKUP_RESULTS = 25
MAX_OPEN_TICKET_QUERY_RECORDS = MAX_TICKET_LOOKUP_RESULTS
MAX_SERVICE_CALL_LOOKUP_RESULTS = 25
MAX_SERVICE_CALL_NAME_LENGTH = 240
MAX_SERVICE_CALL_DETAIL_LENGTH = 2000
MAX_AUTOTASK_IN_FILTER_VALUES = 500

WORK_LOCATION_SUMMARY_PREFIXES = {
    WorkLocation.REMOTE: "Remote",
    WorkLocation.ON_SITE: "On-Site",
}
MIN_COMPANY_SEARCH_CHARACTERS = 3
REMOTE_SERVICE_CALL_PATTERN = re.compile(r"\bremote\b", re.IGNORECASE)
ON_SITE_SERVICE_CALL_PATTERN = re.compile(r"\bon[\s-]?site\b", re.IGNORECASE)
SUMMARY_WORK_LOCATION_PREFIX_PATTERN = re.compile(
    r"^\s*(?P<prefix>on[\s-]?site|remote)\b(?:\s*[:\-]\s*|\s+|$)(?P<summary>.*)\Z",
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

# SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS keeps today's service-call list long
# enough for a tap-to-start action to reuse the server-resolved Autotask data.
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

# _TICKET_STATUS_CACHE stores ticket status picklist labels keyed by tenant URL.
_TICKET_STATUS_CACHE: dict[str, _AutotaskCacheEntry] = {}

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

    # external_id stores the remote Autotask time-entry ID when available.
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

    # detected_work_location is set only when Remote or On-Site is found in the service-call details.
    detected_work_location: WorkLocation | None

    # work_location_label is the user-facing result of the service-call details keyword scan.
    work_location_label: str

    # ticket_number is the Autotask ticket number that will be stored on the started job.
    ticket_number: str

    # ticket_title is the associated Autotask ticket title shown in the service-call list.
    ticket_title: str

    # ticket_description is bounded Autotask ticket context stored on the job after the click.
    ticket_description: str | None

    # client_name is the selected Autotask company name stored on the new active job.
    client_name: str

    # autotask_company_id is the selected Autotask company/account ID stored on the new active job.
    autotask_company_id: int

    # start_datetime_utc is kept only for stable sorting and concise audit context.
    start_datetime_utc: datetime | None


class AutotaskSubmissionError(RuntimeError):
    """Raised for configuration or remote Autotask failures."""


class BaseAutotaskProvider:
    """Interface implemented by all Autotask providers."""

    provider_name = "base"

    def submit_job(self, job: Job) -> AutotaskSubmissionResult:
        """Submit a reviewed job to an external destination."""

        raise NotImplementedError

    def update_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Update an existing external time entry for a submitted job."""

        raise NotImplementedError

    def delete_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Delete an existing external time entry for a submitted job."""

        raise NotImplementedError

    def test_connectivity(self) -> AutotaskConnectivityResult:
        """Return whether this provider is ready for the job workflow."""

        raise NotImplementedError

    def list_open_tickets_for_client(self, client_name: str, autotask_company_id: int | None = None) -> list[AutotaskTicketOption]:
        """Return open ticket options for the supplied client name."""

        raise NotImplementedError

    def search_companies(self, query_text: str) -> list[AutotaskCompanyOption]:
        """Return matching Autotask companies for an autocomplete query."""

        raise NotImplementedError

    def list_todays_service_calls_for_resource(
        self,
        current_time_utc: datetime | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return today's service calls for the configured Autotask resource."""

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
    correct the leading Remote/On-Site value before submission. Local storage
    still keeps that work mode structured in `work_location`, so this parser
    accepts common visible prefixes and returns clean reviewer notes.
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
    """Return Remote or On-Site when a service-call details field names one."""

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


def work_location_label_for_detection(work_location: WorkLocation | None) -> str:
    """Return the service-call list label for a detected work location."""

    if work_location is None:
        return "Not specified"

    return WORK_LOCATION_SUMMARY_PREFIXES[work_location]


def _safe_service_call_text(raw_text: Any, fallback_text: str, max_length: int) -> str:
    """Return bounded Autotask display text for service-call and ticket data."""

    safe_text = str(raw_text or "").strip()
    if not safe_text:
        safe_text = fallback_text

    return safe_text[:max_length]


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


def build_safe_submission_snapshot(job: Job) -> dict[str, Any]:
    """Build a non-secret snapshot of local job data used for submission."""

    summary_notes_for_autotask = build_autotask_summary_notes(job)
    return {
        "job_id": job.id,
        "ticket_number": job.ticket_number,
        "ticket_status": job.ticket_status.value if job.ticket_status else None,
        "startDateTime": format_autotask_datetime(job.rounded_start_utc),
        "endDateTime": format_autotask_datetime(job.rounded_end_utc) if job.rounded_end_utc else None,
        "hoursWorked": str(_job_duration_hours(job)) if job.rounded_end_utc else None,
        "work_location": _work_location_for_job(job).value,
        "summaryNotesLength": len(summary_notes_for_autotask),
    }


class MockAutotaskProvider(BaseAutotaskProvider):
    """Local provider that marks submissions successful without external calls."""

    provider_name = "mock"

    def submit_job(self, job: Job) -> AutotaskSubmissionResult:
        """Return a deterministic mock external ID for end-to-end tests."""

        snapshot = build_safe_submission_snapshot(job)
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=f"mock-time-entry-{job.id}",
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-entry update tests."""

        snapshot = build_safe_submission_snapshot(job)
        snapshot["operation"] = "update_time_entry"
        snapshot["external_id"] = external_id
        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Return a deterministic success for submitted-entry delete tests."""

        snapshot = {
            "operation": "delete_time_entry",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
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

    def list_open_tickets_for_client(self, client_name: str, autotask_company_id: int | None = None) -> list[AutotaskTicketOption]:
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
            ),
            AutotaskTicketOption(
                ticket_number="T20260616.0002",
                title=f"Mock follow-up ticket for {safe_client_name}",
                description=f"Mock follow-up description for {safe_client_name}.",
                status_label="Follow Up",
                company_name=safe_client_name,
            ),
        ]

    def search_companies(self, query_text: str) -> list[AutotaskCompanyOption]:
        """Return deterministic company options for local autocomplete testing."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_COMPANY_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 3 characters before searching Autotask companies.")

        return [
            AutotaskCompanyOption(company_id=1001, company_name=f"{safe_query_text} Services"),
            AutotaskCompanyOption(company_id=1002, company_name=f"{safe_query_text} Holdings"),
        ]

    def list_todays_service_calls_for_resource(
        self,
        current_time_utc: datetime | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return deterministic service-call options for local mobile testing."""

        # current_time_utc is accepted so the mock matches the live provider
        # contract; mock data is intentionally static for stable tests.
        _ = current_time_utc
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
                client_name="Scheduled Service Client",
                autotask_company_id=1001,
                start_datetime_utc=None,
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
                client_name="Scheduled Service Client",
                autotask_company_id=1001,
                start_datetime_utc=None,
            ),
        ]


class LiveAutotaskProvider(BaseAutotaskProvider):
    """Autotask REST API provider for reviewed time-entry submission."""

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

        headers = {
            "ApiIntegrationCode": self.application_settings.autotask_api_integration_code or "",
            "UserName": self.application_settings.autotask_username or "",
            "Secret": self.application_settings.autotask_secret or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.application_settings.autotask_impersonation_resource_id is not None:
            headers["ImpersonationResourceId"] = str(self.application_settings.autotask_impersonation_resource_id)

        return headers

    def _client(self, timeout_seconds: float = 30.0) -> httpx.Client:
        """Return a short-lived HTTP client for Autotask calls."""

        base_url = (self.application_settings.autotask_base_url or "").rstrip("/")
        return httpx.Client(base_url=base_url, headers=self._headers(), timeout=timeout_seconds)

    def _cache_namespace(self) -> str:
        """Return the non-secret namespace used for tenant-specific cache keys."""

        return (self.application_settings.autotask_base_url or "").rstrip("/")

    def _open_ticket_selection_cache_key(self, client_name: str, autotask_company_id: int | None) -> tuple[str, str, int | None]:
        """Return the cache key for a recently displayed open-ticket list."""

        normalized_client_name = client_name.strip().casefold()
        return (self._cache_namespace(), normalized_client_name, autotask_company_id)

    def _service_call_selection_cache_key(
        self,
        resource_id: int,
        local_day_start_utc: datetime,
        local_day_end_utc: datetime,
    ) -> tuple[str, int, str, str]:
        """Return the cache key for today's service-call start list."""

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
            raise AutotaskSubmissionError(
                f"{action_description} failed with Autotask HTTP {response.status_code}: {safe_error_detail}"
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
        response = client.post(endpoint_path, json=paged_query_payload)
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
            response = client.post(str(next_page_url), json=paged_query_payload)
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
                "IncludeFields": ["id", "ticketNumber", "title", "description", "companyID"],
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

    def _query_companies_by_ids(self, client: httpx.Client, company_ids: list[int]) -> dict[int, dict[str, Any]]:
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
            detected_work_location = detect_work_location_from_service_call_details(service_call_details)
            start_datetime_utc = _parse_autotask_datetime(service_call_record.get("startDateTime"))

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
                        client_name=client_name,
                        autotask_company_id=company_id,
                        start_datetime_utc=start_datetime_utc,
                    )
                )
                if len(service_call_options) >= MAX_SERVICE_CALL_LOOKUP_RESULTS:
                    return service_call_options

        return service_call_options

    def _workflow_configuration_gaps(self) -> list[str]:
        """Return missing settings that would prevent the full Autotask workflow."""

        required_workflow_values = {
            "AUTOTASK_RESOURCE_ID": self.application_settings.autotask_resource_id,
            "AUTOTASK_ROLE_ID": self.application_settings.autotask_role_id,
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
        response = client.post(endpoint_path, json=connectivity_query_payload)
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
                    "Use scripts/discover_autotask_ids.py to look up role, billing code, and ticket status IDs after API credentials work.",
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

    def _query_ticket_status_labels(self, client: httpx.Client) -> dict[int, str]:
        """Return Autotask Tickets.status picklist values as ID-to-label mappings."""

        cache_key = self._cache_namespace()
        cached_status_labels = _get_cached_value(_TICKET_STATUS_CACHE, cache_key)
        if isinstance(cached_status_labels, dict):
            return cached_status_labels

        response = client.get("/Tickets/entityInformation/fields/status")
        if response.status_code == 404:
            response = client.get("/Tickets/entityInformation/fields")
        self._raise_for_safe_response(response, "Autotask ticket status metadata query")

        response_payload = response.json()
        status_field: dict[str, Any] | None = None
        if isinstance(response_payload, dict) and "picklistValues" in response_payload:
            status_field = response_payload
        else:
            fields = response_payload.get("fields") if isinstance(response_payload, dict) else response_payload
            if isinstance(fields, list):
                for field_record in fields:
                    if isinstance(field_record, dict) and field_record.get("name") == "status":
                        status_field = field_record
                        break

        if status_field is None:
            _set_cached_value(_TICKET_STATUS_CACHE, cache_key, {})
            return {}

        picklist_values = status_field.get("picklistValues") or status_field.get("PicklistValues") or []
        status_labels: dict[int, str] = {}
        if not isinstance(picklist_values, list):
            _set_cached_value(_TICKET_STATUS_CACHE, cache_key, status_labels)
            return status_labels

        for picklist_value in picklist_values:
            if not isinstance(picklist_value, dict):
                continue

            raw_status_id = picklist_value.get("value") or picklist_value.get("id")
            status_label = picklist_value.get("label") or picklist_value.get("name")
            if raw_status_id is None or status_label is None:
                continue

            try:
                status_labels[int(raw_status_id)] = str(status_label)
            except (TypeError, ValueError):
                continue

        _set_cached_value(_TICKET_STATUS_CACHE, cache_key, status_labels)
        return status_labels

    def _query_companies_by_name(self, client: httpx.Client, client_name: str) -> list[dict[str, Any]]:
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

    def _query_company_by_id(self, client: httpx.Client, company_id: int) -> dict[str, Any] | None:
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
            "IncludeFields": ["id", "ticketNumber", "title", "description", "status", "completedDate"],
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

            ticket_options.append(
                AutotaskTicketOption(
                    ticket_number=ticket_number,
                    title=str(ticket.get("title") or "Untitled ticket")[:240],
                    description=str(ticket.get("description") or "").strip()[:8000] or None,
                    status_label=status_labels.get(status_id, str(raw_status_id or "Unknown")),
                    company_name=company_name,
                )
            )

        return ticket_options

    def list_open_tickets_for_client(self, client_name: str, autotask_company_id: int | None = None) -> list[AutotaskTicketOption]:
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
            companies: list[dict[str, Any]]
            if autotask_company_id is not None:
                selected_company = self._query_company_by_id(client, autotask_company_id)
                companies = [selected_company] if selected_company is not None else []
            else:
                companies = self._query_companies_by_name(client, safe_client_name)

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

    def search_companies(self, query_text: str) -> list[AutotaskCompanyOption]:
        """Return active Autotask companies matching a user-entered query."""

        safe_query_text = query_text.strip()
        if len(safe_query_text) < MIN_COMPANY_SEARCH_CHARACTERS:
            raise AutotaskSubmissionError("Type at least 3 characters before searching Autotask companies.")

        with self._client() as client:
            companies = self._query_companies_by_name(client, safe_query_text)

        return [
            AutotaskCompanyOption(
                company_id=int(company["id"]),
                company_name=str(company.get("companyName") or "Unnamed company")[:120],
            )
            for company in companies
        ]

    def list_todays_service_calls_for_resource(
        self,
        current_time_utc: datetime | None = None,
    ) -> list[AutotaskServiceCallOption]:
        """Return today's service calls assigned to AUTOTASK_RESOURCE_ID."""

        resource_id = self.application_settings.autotask_resource_id
        if resource_id is None:
            raise AutotaskSubmissionError("AUTOTASK_RESOURCE_ID is required before loading today's service calls.")

        safe_current_time_utc = ensure_utc(current_time_utc or now_utc())
        local_day_start_utc, local_day_end_utc = local_day_bounds_utc(local_date_for(safe_current_time_utc))
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
            company_records_by_id = self._query_companies_by_ids(client, company_ids)
            service_call_options = self._build_service_call_options(
                service_call_records=service_call_records,
                service_call_ticket_records=service_call_ticket_records,
                service_call_ticket_resource_records=service_call_ticket_resource_records,
                ticket_records_by_id=ticket_records_by_id,
                company_records_by_id=company_records_by_id,
            )[:MAX_SERVICE_CALL_LOOKUP_RESULTS]

        _set_cached_value(
            _SERVICE_CALL_SELECTION_CACHE,
            cache_key,
            service_call_options,
            SERVICE_CALL_SELECTION_CACHE_TTL_SECONDS,
        )
        return service_call_options

    def _query_ticket_id(self, client: httpx.Client, ticket_number: str) -> int:
        """Find the Autotask ticket ID for the reviewed ticket number."""

        query_payload = {"filter": [{"op": "eq", "field": "ticketNumber", "value": ticket_number}]}
        tickets = self._query_paginated_items(
            client,
            endpoint_path="/Tickets/query",
            query_payload=query_payload,
            action_description="Autotask ticket number lookup",
        )
        if not tickets:
            raise AutotaskSubmissionError(f"No Autotask ticket found for ticket number {ticket_number}.")

        ticket_id = tickets[0].get("id")
        if ticket_id is None:
            raise AutotaskSubmissionError("Autotask ticket query did not return an ID.")

        return int(ticket_id)

    def _update_ticket_status(self, client: httpx.Client, ticket_id: int, ticket_status: TicketStatus | None) -> None:
        """Update the Autotask ticket status when a tenant picklist ID is configured."""

        if ticket_status is None:
            return

        status_id = self.application_settings.autotask_status_id_map.get(ticket_status.value)
        if status_id is None:
            return

        response = client.patch("/Tickets", json={"id": ticket_id, "status": status_id})
        self._raise_for_safe_response(response, "Autotask ticket status update")

    def _time_entry_payload(self, job: Job, *, ticket_id: int | None = None) -> dict[str, Any]:
        """Build the editable TimeEntries fields shared by create and update."""

        if job.rounded_end_utc is None:
            raise AutotaskSubmissionError("Job has no rounded end time.")

        payload: dict[str, Any] = {
            "startDateTime": format_autotask_datetime(job.rounded_start_utc),
            "endDateTime": format_autotask_datetime(job.rounded_end_utc),
            "hoursWorked": float(_job_duration_hours(job)),
            "summaryNotes": build_autotask_summary_notes(job),
        }
        if ticket_id is not None:
            if self.application_settings.autotask_resource_id is None:
                raise AutotaskSubmissionError("AUTOTASK_RESOURCE_ID is required before Autotask submission.")
            if self.application_settings.autotask_role_id is None:
                raise AutotaskSubmissionError("AUTOTASK_ROLE_ID is required before Autotask submission.")
            payload.update(
                {
                    "ticketID": ticket_id,
                    "resourceID": self.application_settings.autotask_resource_id,
                    "roleID": self.application_settings.autotask_role_id,
                    "timeEntryType": self.application_settings.autotask_time_entry_type,
                }
            )

        return payload

    def _create_time_entry(self, client: httpx.Client, job: Job, ticket_id: int) -> str:
        """Create the Autotask TimeEntries row for the accepted job."""

        payload = self._time_entry_payload(job, ticket_id=ticket_id)
        response = client.post("/TimeEntries", json=payload)
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
        response = client.patch("/TimeEntries", json=payload)
        self._raise_for_safe_response(response, "Autotask time entry update")

    def _delete_time_entry(self, client: httpx.Client, external_id: str) -> None:
        """Delete an existing Autotask TimeEntries row by remote ID."""

        time_entry_id = _coerce_positive_autotask_id(external_id)
        if time_entry_id is None:
            raise AutotaskSubmissionError("Existing Autotask time entry ID is required before deleting.")

        response = client.delete(f"/TimeEntries/{time_entry_id}")
        self._raise_for_safe_response(response, "Autotask time entry deletion")

    def submit_job(self, job: Job) -> AutotaskSubmissionResult:
        """Submit a reviewed job to the Autotask REST API."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask submission.")

        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "resourceID": self.application_settings.autotask_resource_id,
                "roleID": self.application_settings.autotask_role_id,
                "timeEntryType": self.application_settings.autotask_time_entry_type,
                "impersonationResourceIDConfigured": self.application_settings.autotask_impersonation_resource_id is not None,
            }
        )
        try:
            with self._client() as client:
                ticket_id = self._query_ticket_id(client, job.ticket_number)
                self._update_ticket_status(client, ticket_id, job.ticket_status)
                external_id = self._create_time_entry(client, job, ticket_id)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=None,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def update_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Update an existing Autotask time entry from reviewed submitted fields."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask time entry updates.")

        snapshot = build_safe_submission_snapshot(job)
        snapshot.update(
            {
                "operation": "update_time_entry",
                "external_id": external_id,
                "impersonationResourceIDConfigured": self.application_settings.autotask_impersonation_resource_id is not None,
            }
        )
        try:
            with self._client() as client:
                ticket_id = self._query_ticket_id(client, job.ticket_number)
                self._update_ticket_status(client, ticket_id, job.ticket_status)
                self._update_time_entry(client, job, external_id)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

        return AutotaskSubmissionResult(
            provider=self.provider_name,
            succeeded=True,
            external_id=external_id,
            safe_error=None,
            request_snapshot=snapshot,
        )

    def delete_time_entry(self, job: Job, external_id: str) -> AutotaskSubmissionResult:
        """Delete an existing Autotask time entry from a submitted job."""

        snapshot = {
            "operation": "delete_time_entry",
            "job_id": job.id,
            "ticket_number": job.ticket_number,
            "external_id": external_id,
            "impersonationResourceIDConfigured": self.application_settings.autotask_impersonation_resource_id is not None,
        }
        try:
            with self._client() as client:
                self._delete_time_entry(client, external_id)
        except (httpx.HTTPError, AutotaskSubmissionError) as exc:
            return AutotaskSubmissionResult(
                provider=self.provider_name,
                succeeded=False,
                external_id=external_id,
                safe_error=str(exc),
                request_snapshot=snapshot,
            )

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

    return _run_autotask_connectivity_check(application_settings)
