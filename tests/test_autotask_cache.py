"""Tests for Autotask lookup caching and paginated query handling."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from job_logger.config import settings
from job_logger.enums import JobStatus, TicketStatus, WorkLocation
from job_logger.models import Job
from job_logger.services.autotask import (
    _COMPANY_ID_CACHE,
    _COMPANY_SEARCH_CACHE,
    _OPEN_TICKET_SELECTION_CACHE,
    _START_CONNECTIVITY_CACHE,
    _TICKET_STATUS_CACHE,
    AutotaskConnectivityResult,
    AutotaskSubmissionError,
    LiveAutotaskProvider,
)
from job_logger.services.autotask import (
    test_autotask_connectivity as run_autotask_connectivity,
)
from job_logger.services.autotask import (
    test_cached_autotask_connectivity_for_start as run_cached_autotask_connectivity_for_start,
)


class FakeAutotaskResponse:
    """Small response double that mimics the httpx fields used by the provider."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        """Store a deterministic response payload and HTTP status code."""

        # payload is the JSON object returned by the fake Autotask endpoint.
        self.payload = payload

        # status_code lets tests exercise the same safe status handling path as httpx.
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        """Return the fake JSON body."""

        return self.payload


class FakeCompanyQueryClient:
    """Fake Autotask client that returns two company pages for one query."""

    def __init__(self) -> None:
        """Initialize counters used to prove cache hits avoid new API calls."""

        # post_call_count counts initial query and next-page POST requests.
        self.post_call_count = 0

        # get_call_count counts any incorrect GET follow-up requests.
        self.get_call_count = 0

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return company query pages using Autotask's POST pagination method."""

        self.post_call_count += 1
        assert json["MaxRecords"] == 500
        if endpoint_path == "/Companies/query/next-page":
            return FakeAutotaskResponse(
                {
                    "items": [{"id": 1001, "companyName": "Acme", "isActive": True}],
                    "pageDetails": {},
                }
            )

        assert endpoint_path == "/Companies/query"
        return FakeAutotaskResponse(
            {
                "items": [{"id": 2002, "companyName": "Acme Zeta", "isActive": True}],
                "pageDetails": {"nextPageUrl": "/Companies/query/next-page"},
            }
        )

    def get(self, next_page_url: str) -> FakeAutotaskResponse:
        """Fail the test if the provider uses GET for POST query pagination."""

        self.get_call_count += 1
        raise AssertionError(f"Autotask POST query pagination must not use GET: {next_page_url}")


class FakeTicketStatusClient:
    """Fake Autotask client that returns ticket status metadata once."""

    def __init__(self) -> None:
        """Initialize a call counter used to prove status cache behavior."""

        # get_call_count counts metadata requests.
        self.get_call_count = 0

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Return ticket status picklist values."""

        self.get_call_count += 1
        assert endpoint_path == "/Tickets/entityInformation/fields/status"
        return FakeAutotaskResponse(
            {
                "picklistValues": [
                    {"value": "1", "label": "In Progress"},
                    {"value": "5", "label": "Complete"},
                ]
            }
        )


class FakeOpenTicketLookupClient:
    """Fake Autotask client that exposes company, status, and ticket lookup calls."""

    def __init__(self) -> None:
        """Initialize counters used to prove open-ticket cache behavior."""

        # company_query_count counts selected-company metadata requests.
        self.company_query_count = 0

        # ticket_query_count counts live Tickets/query requests.
        self.ticket_query_count = 0

        # status_lookup_count counts ticket status picklist metadata requests.
        self.status_lookup_count = 0

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return company or ticket query responses based on the requested endpoint."""

        if endpoint_path == "/Companies/query":
            assert json["MaxRecords"] == 500
            self.company_query_count += 1
            return FakeAutotaskResponse(
                {
                    "items": [{"id": 1001, "companyName": "Fast Client", "isActive": True}],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/Tickets/query":
            assert json["MaxRecords"] == 25
            assert json["IncludeFields"] == ["id", "ticketNumber", "title", "description", "status", "completedDate"]
            assert {"op": "eq", "field": "companyID", "value": 1001} in json["filter"]
            assert {"op": "notExist", "field": "completedDate"} in json["filter"]
            assert {"op": "noteq", "field": "status", "value": 5} in json["filter"]
            self.ticket_query_count += 1
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "ticketNumber": "T20260616.0001",
                            "title": "Cached open ticket",
                            "description": "Cached open ticket description.",
                            "status": 1,
                        },
                        {
                            "ticketNumber": "T20260616.0002",
                            "title": "Completed ticket should not be returned",
                            "status": 5,
                        },
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Return ticket status picklist values for open-ticket filtering."""

        self.status_lookup_count += 1
        assert endpoint_path == "/Tickets/entityInformation/fields/status"
        return FakeAutotaskResponse(
            {
                "picklistValues": [
                    {"value": "1", "label": "In Progress"},
                    {"value": "5", "label": "Complete"},
                ]
            }
        )


class FakeEmptyCompanyQueryClient:
    """Fake Autotask client that returns no companies for each live query."""

    def __init__(self) -> None:
        """Initialize a call counter to prove empty results are not authoritative."""

        # post_call_count counts live Autotask company query attempts.
        self.post_call_count = 0

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return an empty company page while preserving query assertions."""

        self.post_call_count += 1
        assert endpoint_path == "/Companies/query"
        assert json["MaxRecords"] == 500
        return FakeAutotaskResponse({"items": [], "pageDetails": {}})


class FakeConnectivityContext:
    """Context manager that returns a fake Autotask client for diagnostics."""

    def __init__(self, fake_client: object) -> None:
        """Store the fake client returned to the provider."""

        # fake_client is the object used by LiveAutotaskProvider inside `with`.
        self.fake_client = fake_client

    def __enter__(self) -> object:
        """Return the fake client to the provider connectivity check."""

        return self.fake_client

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        """Do not suppress provider exceptions in connectivity tests."""

        return False


class FakeCompanyConnectivityFailureClient:
    """Fake Autotask client that denies the Companies workflow probe."""

    def __init__(self) -> None:
        """Initialize a flag proving later checks were not attempted."""

        # get_call_count would increase if ticket metadata ran after failure.
        self.get_call_count = 0

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return an Autotask permission error for the Companies query probe."""

        assert endpoint_path == "/Companies/query"
        assert json["MaxRecords"] == 1
        return FakeAutotaskResponse(
            {"errors": ["The logged in Resource does not have the adequate permissions to query this entity type."]},
            status_code=500,
        )

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Fail if later connectivity checks run after Companies failure."""

        self.get_call_count += 1
        return FakeAutotaskResponse({})


class FakeTimeEntryCreateClient:
    """Fake Autotask client that captures the TimeEntries create payload."""

    def __init__(self) -> None:
        """Initialize payload capture used by the TimeEntries test."""

        # posted_payload stores the exact JSON body sent to the fake endpoint.
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture one TimeEntries POST and return a successful response."""

        assert endpoint_path == "/TimeEntries"
        self.posted_payload = dict(json)
        return FakeAutotaskResponse({"itemId": 987654})


class FakeConnectivityProvider:
    """Fake provider that counts connectivity checks for cache tests."""

    provider_name = "autotask"

    def __init__(self) -> None:
        """Initialize the live-check counter."""

        # check_count increments each time the fake provider is asked to test connectivity.
        self.check_count = 0

    def test_connectivity(self) -> AutotaskConnectivityResult:
        """Return a successful dependency result while recording the call."""

        self.check_count += 1
        return AutotaskConnectivityResult(
            provider=self.provider_name,
            available=True,
            summary="Fake Autotask connectivity succeeded.",
            checked_operations=("configuration", "companies", "tickets"),
        )


def _live_test_provider() -> LiveAutotaskProvider:
    """Return a configured live provider without real Autotask credentials."""

    test_settings = replace(
        settings,
        autotask_provider="autotask",
        autotask_base_url="https://example.test/ATServicesRest/V1.0",
        autotask_username="api-user-key",
        autotask_secret="api-secret",
        autotask_api_integration_code="integration-code",
        autotask_resource_id=1,
        autotask_role_id=2,
        autotask_billing_code_id=24746620,
        autotask_status_in_progress_id=1,
        autotask_status_waiting_customer_id=2,
        autotask_status_waiting_parts_id=3,
        autotask_status_follow_up_id=4,
        autotask_status_complete_id=5,
    )
    return LiveAutotaskProvider(test_settings)


def _clear_autotask_lookup_caches() -> None:
    """Clear module-level lookup caches so each test is deterministic."""

    _COMPANY_SEARCH_CACHE.clear()
    _COMPANY_ID_CACHE.clear()
    _TICKET_STATUS_CACHE.clear()
    _OPEN_TICKET_SELECTION_CACHE.clear()
    _START_CONNECTIVITY_CACHE.clear()


def test_company_lookup_uses_pagination_and_cache() -> None:
    """Company lookup should fetch paged results once and cache them for reuse."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeCompanyQueryClient()

    first_lookup = provider._query_companies_by_name(fake_client, "Acme")
    second_lookup = provider._query_companies_by_name(fake_client, "Acme")

    assert [company["companyName"] for company in first_lookup] == ["Acme", "Acme Zeta"]
    assert second_lookup == first_lookup
    assert fake_client.post_call_count == 2
    assert fake_client.get_call_count == 0


def test_empty_company_lookup_does_not_block_future_live_query() -> None:
    """Empty company cache results should not prevent a later Autotask lookup."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeEmptyCompanyQueryClient()

    first_lookup = provider._query_companies_by_name(fake_client, "Not Cached")
    second_lookup = provider._query_companies_by_name(fake_client, "Not Cached")

    assert first_lookup == []
    assert second_lookup == []
    assert fake_client.post_call_count == 2


def test_ticket_status_lookup_uses_cache() -> None:
    """Ticket status metadata should be cached after the first lookup."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeTicketStatusClient()

    first_lookup = provider._query_ticket_status_labels(fake_client)
    second_lookup = provider._query_ticket_status_labels(fake_client)

    assert first_lookup == {1: "In Progress", 5: "Complete"}
    assert second_lookup == first_lookup
    assert fake_client.get_call_count == 1


def test_open_ticket_lookup_reuses_recent_server_verified_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting a displayed ticket should not re-query live Autotask immediately."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeOpenTicketLookupClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake client while matching the provider client signature."""

        # timeout_seconds is accepted so the fake matches LiveAutotaskProvider._client.
        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    provider._query_companies_by_name(fake_client, "Fast Client")
    first_lookup = provider.list_open_tickets_for_client("Fast Client", autotask_company_id=1001)
    second_lookup = provider.list_open_tickets_for_client("Fast Client", autotask_company_id=1001)

    assert [ticket.ticket_number for ticket in first_lookup] == ["T20260616.0001"]
    assert second_lookup == first_lookup
    assert fake_client.company_query_count == 1
    assert fake_client.ticket_query_count == 1
    assert fake_client.status_lookup_count == 1


def test_start_connectivity_check_uses_short_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start Work should not run a live Autotask probe for every quick tap."""

    _clear_autotask_lookup_caches()
    fake_provider = FakeConnectivityProvider()
    provider_settings = _live_test_provider().application_settings

    monkeypatch.setattr("job_logger.services.autotask.get_autotask_provider", lambda application_settings: fake_provider)

    first_result = run_cached_autotask_connectivity_for_start(provider_settings)
    second_result = run_cached_autotask_connectivity_for_start(provider_settings)

    assert first_result.available is True
    assert second_result == first_result
    assert fake_provider.check_count == 1


def test_debug_connectivity_check_bypasses_start_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The debug Autotask test should always run a fresh provider check."""

    _clear_autotask_lookup_caches()
    fake_provider = FakeConnectivityProvider()
    provider_settings = _live_test_provider().application_settings

    monkeypatch.setattr("job_logger.services.autotask.get_autotask_provider", lambda application_settings: fake_provider)

    cached_result = run_cached_autotask_connectivity_for_start(provider_settings)
    fresh_debug_result = run_autotask_connectivity(provider_settings)

    assert cached_result.available is True
    assert fresh_debug_result.available is True
    assert fake_provider.check_count == 2


def test_blank_impersonation_resource_omits_autotask_header() -> None:
    """Blank impersonation config should not send Autotask's impersonation header."""

    provider = _live_test_provider()
    assert provider.application_settings.autotask_impersonation_resource_id is None
    assert "ImpersonationResourceId" not in provider._headers()


def test_connectivity_result_identifies_company_query_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autotask diagnostics should identify permission failures clearly."""

    provider = _live_test_provider()
    fake_client = FakeCompanyConnectivityFailureClient()

    def fake_client_context(timeout_seconds: float = 10.0) -> FakeConnectivityContext:
        """Return the fake context manager while accepting the provider timeout."""

        # timeout_seconds is accepted so the fake matches LiveAutotaskProvider._client.
        assert timeout_seconds == 10.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    connectivity_result = provider.test_connectivity()

    assert connectivity_result.available is False
    assert connectivity_result.failed_operation == "companies"
    assert connectivity_result.checked_operations == ("configuration",)
    assert "during companies" in connectivity_result.summary
    assert "adequate permissions" in connectivity_result.summary
    assert any("security level permission" in tip for tip in connectivity_result.tips)
    assert fake_client.get_call_count == 0


def test_safe_autotask_error_detail_extracts_nested_error_messages() -> None:
    """Submission failures should include safe Autotask body details."""

    provider = _live_test_provider()
    response = httpx.Response(
        500,
        json={
            "errors": [
                {"message": "The field billingCodeID is invalid for this ticket."},
                {"Detail": "Use a billing code available to the selected resource."},
            ],
        },
    )

    with pytest.raises(AutotaskSubmissionError) as exc_info:
        provider._raise_for_safe_response(response, "Autotask time entry creation")

    error_message = str(exc_info.value)
    assert "Autotask time entry creation failed with Autotask HTTP 500" in error_message
    assert "billingCodeID is invalid" in error_message
    assert "Use a billing code available" in error_message


def test_time_entry_creation_omits_billing_code_id() -> None:
    """Ticket TimeEntries must not try to change Autotask allocation code."""

    provider = _live_test_provider()
    fake_client = FakeTimeEntryCreateClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="time-entry-payload-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Payload must not include allocation code.",
        description_text="Payload must not include allocation code.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    external_id = provider._create_time_entry(fake_client, job, ticket_id=123456)

    assert external_id == "987654"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 1
    assert fake_client.posted_payload["roleID"] == 2
    assert fake_client.posted_payload["timeEntryType"] == 2
    assert fake_client.posted_payload["summaryNotes"] == "Remote Payload must not include allocation code."
    assert "billingCodeID" not in fake_client.posted_payload


def test_time_entry_summary_notes_use_hidden_work_location_prefix() -> None:
    """Autotask summary notes receive the stored work-location prefix only at submission."""

    provider = _live_test_provider()
    fake_client = FakeTimeEntryCreateClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="time-entry-work-location-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Remote replaced the router and verified service.",
        description_text="Remote replaced the router and verified service.",
        work_location=WorkLocation.ON_SITE,
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    external_id = provider._create_time_entry(fake_client, job, ticket_id=123456)

    assert external_id == "987654"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["summaryNotes"] == "On-Site replaced the router and verified service."
