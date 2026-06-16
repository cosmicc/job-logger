"""Autotask time-entry submission providers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from job_logger.config import Settings, settings
from job_logger.enums import TicketStatus
from job_logger.models import Job
from job_logger.time_utils import format_autotask_datetime, rounded_duration_minutes


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


class AutotaskSubmissionError(RuntimeError):
    """Raised for configuration or remote Autotask failures."""


class BaseAutotaskProvider:
    """Interface implemented by all Autotask providers."""

    provider_name = "base"

    def submit_job(self, job: Job) -> AutotaskSubmissionResult:
        """Submit a reviewed job to an external destination."""

        raise NotImplementedError


def _job_duration_hours(job: Job) -> Decimal:
    """Return rounded duration as decimal hours for Autotask."""

    if job.rounded_end_utc is None:
        raise AutotaskSubmissionError("Job has no rounded end time.")

    minutes = rounded_duration_minutes(job.rounded_start_utc, job.rounded_end_utc)
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_safe_submission_snapshot(job: Job) -> dict[str, Any]:
    """Build a non-secret snapshot of local job data used for submission."""

    return {
        "job_id": job.id,
        "ticket_number": job.ticket_number,
        "ticket_status": job.ticket_status.value if job.ticket_status else None,
        "startDateTime": format_autotask_datetime(job.rounded_start_utc),
        "endDateTime": format_autotask_datetime(job.rounded_end_utc) if job.rounded_end_utc else None,
        "hoursWorked": str(_job_duration_hours(job)) if job.rounded_end_utc else None,
        "summaryNotesLength": len(job.summary_notes or ""),
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


class LiveAutotaskProvider(BaseAutotaskProvider):
    """Autotask REST API provider for reviewed time-entry submission."""

    provider_name = "autotask"

    def __init__(self, application_settings: Settings) -> None:
        """Store settings and validate required live Autotask values."""

        self.application_settings = application_settings
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Ensure live Autotask submissions have every required secret and ID."""

        required_values = {
            "AUTOTASK_BASE_URL": self.application_settings.autotask_base_url,
            "AUTOTASK_USERNAME": self.application_settings.autotask_username,
            "AUTOTASK_SECRET": self.application_settings.autotask_secret,
            "AUTOTASK_API_INTEGRATION_CODE": self.application_settings.autotask_api_integration_code,
            "AUTOTASK_RESOURCE_ID": self.application_settings.autotask_resource_id,
            "AUTOTASK_ROLE_ID": self.application_settings.autotask_role_id,
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

    def _client(self) -> httpx.Client:
        """Return a short-lived HTTP client for Autotask calls."""

        base_url = (self.application_settings.autotask_base_url or "").rstrip("/")
        return httpx.Client(base_url=base_url, headers=self._headers(), timeout=30)

    def _query_ticket_id(self, client: httpx.Client, ticket_number: str) -> int:
        """Find the Autotask ticket ID for the reviewed ticket number."""

        query_payload = {"filter": [{"op": "eq", "field": "ticketNumber", "value": ticket_number}]}
        response = client.post("/Tickets/query", json=query_payload)
        response.raise_for_status()
        response_payload = response.json()
        tickets = response_payload.get("items") or response_payload.get("Item") or []
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
        response.raise_for_status()

    def _create_time_entry(self, client: httpx.Client, job: Job, ticket_id: int) -> str:
        """Create the Autotask TimeEntries row for the accepted job."""

        if job.rounded_end_utc is None:
            raise AutotaskSubmissionError("Job has no rounded end time.")

        payload: dict[str, Any] = {
            "ticketID": ticket_id,
            "resourceID": self.application_settings.autotask_resource_id,
            "roleID": self.application_settings.autotask_role_id,
            "timeEntryType": self.application_settings.autotask_time_entry_type,
            "startDateTime": format_autotask_datetime(job.rounded_start_utc),
            "endDateTime": format_autotask_datetime(job.rounded_end_utc),
            "hoursWorked": float(_job_duration_hours(job)),
            "summaryNotes": job.summary_notes or job.description_text or "",
        }
        if self.application_settings.autotask_billing_code_id is not None:
            payload["billingCodeID"] = self.application_settings.autotask_billing_code_id

        response = client.post("/TimeEntries", json=payload)
        response.raise_for_status()
        response_payload = response.json()
        item_id = response_payload.get("itemId") or response_payload.get("id") or response_payload.get("ItemId")
        if item_id is None:
            return "created-without-id"

        return str(item_id)

    def submit_job(self, job: Job) -> AutotaskSubmissionResult:
        """Submit a reviewed job to the Autotask REST API."""

        if not job.ticket_number:
            raise AutotaskSubmissionError("Ticket number is required before Autotask submission.")

        snapshot = build_safe_submission_snapshot(job)
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


def get_autotask_provider(application_settings: Settings = settings) -> BaseAutotaskProvider:
    """Return the configured Autotask provider."""

    if application_settings.autotask_provider == "mock":
        return MockAutotaskProvider()

    if application_settings.autotask_provider == "autotask":
        return LiveAutotaskProvider(application_settings)

    raise AutotaskSubmissionError(f"Unsupported Autotask provider: {application_settings.autotask_provider}")

