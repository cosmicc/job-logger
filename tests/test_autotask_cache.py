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
from job_logger.services import system_health
from job_logger.services.autotask import (
    _COMPANY_ID_CACHE,
    _COMPANY_SEARCH_CACHE,
    _OPEN_TICKET_SELECTION_CACHE,
    _RESOURCE_SEARCH_CACHE,
    _SERVICE_CALL_SELECTION_CACHE,
    _TICKET_SOURCE_CACHE,
    _TICKET_STATUS_CACHE,
    AutotaskConnectivityResult,
    AutotaskSubmissionError,
    LiveAutotaskProvider,
    split_autotask_summary_notes,
)
from job_logger.services.autotask import (
    test_autotask_connectivity as run_autotask_connectivity,
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


class FakeTransportFailureClient:
    """Fake Autotask client that raises a transport-level HTTP error."""

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Simulate Autotask being unreachable before an HTTP response exists."""

        raise httpx.ConnectError("Autotask API is unreachable")


class FakeSuccessfulApiClient:
    """Fake Autotask client that returns one successful API response."""

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Return a success response so the cached health state can clear."""

        return FakeAutotaskResponse({})


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

        # source_lookup_count counts ticket source picklist metadata requests.
        self.source_lookup_count = 0

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
            assert json["IncludeFields"] == [
                "id",
                "ticketNumber",
                "title",
                "description",
                "status",
                "completedDate",
                "source",
            ]
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
                            "source": 11,
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
        """Return ticket metadata picklist values for open-ticket filtering."""

        if endpoint_path == "/Tickets/entityInformation/fields/status":
            self.status_lookup_count += 1
            return FakeAutotaskResponse(
                {
                    "picklistValues": [
                        {"value": "1", "label": "In Progress"},
                        {"value": "5", "label": "Complete"},
                    ]
                }
            )

        if endpoint_path == "/Tickets/entityInformation/fields/source":
            self.source_lookup_count += 1
            return FakeAutotaskResponse(
                {
                    "picklistValues": [
                        {"value": "11", "label": "RMM Alert"},
                    ]
                }
            )

        raise AssertionError(f"Unexpected fake Autotask GET endpoint: {endpoint_path}")


class FakeTicketNotesLookupClient:
    """Fake Autotask client that exposes ticket ID and TicketNotes queries."""

    def __init__(self) -> None:
        """Capture provider query payloads for TicketNotes assertions."""

        # post_requests preserves the exact entity endpoints used by the lookup.
        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return one selected ticket and two note rows."""

        self.post_requests.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            assert json["MaxRecords"] == 1
            assert json["IncludeFields"] == ["id", "ticketNumber"]
            assert json["filter"] == [{"op": "eq", "field": "ticketNumber", "value": "T20260616.0001"}]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 123456, "ticketNumber": "T20260616.0001"},
                    ],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/TicketNotes/query":
            assert json["MaxRecords"] == 100
            assert json["IncludeFields"] == [
                "id",
                "ticketID",
                "title",
                "description",
                "createDateTime",
                "lastActivityDate",
                "noteType",
                "publish",
            ]
            assert json["filter"] == [{"op": "eq", "field": "ticketID", "value": 123456}]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 91001,
                            "ticketID": 123456,
                            "title": "Original customer note",
                            "description": "Customer reported intermittent failures.",
                            "createDateTime": "2026-06-16T12:00:00Z",
                            "lastActivityDate": "2026-06-16T12:30:00Z",
                            "noteType": "Customer",
                            "publish": 1,
                        },
                        {
                            "id": 91002,
                            "ticketID": 123456,
                            "title": "Technician update",
                            "description": "Technician confirmed WAN status before dispatch.",
                            "createDateTime": "2026-06-16T13:00:00Z",
                            "publish": "2",
                        },
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")


class FakeServiceCallLookupClient:
    """Fake Autotask client that exposes the service-call relationship chain."""

    def __init__(self) -> None:
        """Initialize captured requests for endpoint and cache assertions."""

        # post_requests stores each fake Autotask query for later assertions.
        self.post_requests: list[tuple[str, dict[str, Any]]] = []

        # status_lookup_count counts ticket status picklist metadata requests.
        self.status_lookup_count = 0

        # source_lookup_count counts ticket source picklist metadata requests.
        self.source_lookup_count = 0

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return related service-call, ticket, resource, and company records."""

        self.post_requests.append((endpoint_path, dict(json)))
        assert json["MaxRecords"] == 500

        if endpoint_path == "/ServiceCalls/query":
            assert json["IncludeFields"] == ["id", "description", "startDateTime", "endDateTime", "companyID"]
            assert {
                "op": "gte",
                "field": "startDateTime",
                "value": "2026-06-16T04:00:00Z",
            } in json["filter"]
            assert {
                "op": "lt",
                "field": "startDateTime",
                "value": "2026-06-17T04:00:00Z",
            } in json["filter"]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 7001,
                            "description": "Firewall replacement",
                            "startDateTime": "2026-06-16T13:00:00Z",
                            "endDateTime": "2026-06-16T14:00:00Z",
                            "companyID": 1001,
                        },
                        {
                            "id": 7002,
                            "description": "Remote service call assigned to another resource",
                            "startDateTime": "2026-06-16T15:00:00Z",
                            "endDateTime": "2026-06-16T16:00:00Z",
                            "companyID": 1002,
                        },
                    ],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/ServiceCallTickets/query":
            assert json["IncludeFields"] == ["id", "serviceCallID", "ticketID"]
            assert json["filter"] == [{"op": "in", "field": "serviceCallID", "value": [7001, 7002]}]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 8001, "serviceCallID": 7001, "ticketID": 9001},
                        {"id": 8002, "serviceCallID": 7002, "ticketID": 9002},
                    ],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/ServiceCallTicketResources/query":
            assert json["IncludeFields"] == ["id", "resourceID", "serviceCallTicketID"]
            assert {"op": "eq", "field": "resourceID", "value": 1} in json["filter"]
            assert {"op": "in", "field": "serviceCallTicketID", "value": [8001, 8002]} in json["filter"]
            return FakeAutotaskResponse(
                {
                    "items": [{"id": 8101, "resourceID": 1, "serviceCallTicketID": 8001}],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/Tickets/query":
            assert json["IncludeFields"] == ["id", "ticketNumber", "title", "description", "companyID", "status", "source"]
            assert json["filter"] == [{"op": "in", "field": "id", "value": [9001]}]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 9001,
                            "ticketNumber": "T20260616.0007",
                            "title": "Firewall replacement",
                            "description": "Replace firewall and verify VPN.",
                            "companyID": 1001,
                            "status": 1,
                            "source": "Datto Alert",
                        }
                    ],
                    "pageDetails": {},
                }
            )

        if endpoint_path == "/Companies/query":
            assert json["IncludeFields"] == ["id", "companyName", "isActive"]
            assert json["filter"] == [{"op": "in", "field": "id", "value": [1001, 1002]}]
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 1001, "companyName": "Acme Services", "isActive": True},
                        {"id": 1002, "companyName": "Other Client", "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Return ticket metadata picklist values for service-call ticket labels."""

        if endpoint_path == "/Tickets/entityInformation/fields/status":
            self.status_lookup_count += 1
            return FakeAutotaskResponse(
                {
                    "picklistValues": [
                        {"value": "1", "label": "In Progress"},
                        {"value": "5", "label": "Complete"},
                    ]
                }
            )

        if endpoint_path == "/Tickets/entityInformation/fields/source":
            self.source_lookup_count += 1
            return FakeAutotaskResponse(
                {
                    "picklistValues": [
                        {"value": "12", "label": "Datto Alert"},
                    ]
                }
            )
        raise AssertionError(f"Unexpected fake Autotask GET endpoint: {endpoint_path}")

class FakeResourceLookupClient:
    """Fake Autotask client that exposes Resources/query for user setup."""

    def __init__(self) -> None:
        """Initialize captured resource lookup requests."""

        # post_requests records each Resources query for assertions.
        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return one matching resource for every generated name filter."""

        self.post_requests.append((endpoint_path, dict(json)))
        assert endpoint_path == "/Resources/query"
        assert json["MaxRecords"] == 25
        assert json["IncludeFields"] == ["id", "firstName", "lastName", "email"]
        return FakeAutotaskResponse(
            {
                "items": [
                    {
                        "id": 42,
                        "firstName": "Joe",
                        "lastName": "Blow",
                        "email": "joe.blow@example.test",
                    }
                ],
                "pageDetails": {},
            }
        )

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Fail if resource lookup performs unexpected metadata GET calls."""

        raise AssertionError(f"Unexpected fake Autotask GET endpoint: {endpoint_path}")


class FakeResourceServiceDeskRoleListClient:
    """Fake Autotask client that exposes active roles and role names."""

    def __init__(self) -> None:
        """Initialize captured role lookup requests."""

        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return active roles with one duplicate default row for de-duplication."""

        self.post_requests.append((endpoint_path, dict(json)))
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 10, "resourceID": 42, "roleID": 9, "isDefault": False, "isActive": True},
                        {"id": 11, "resourceID": 42, "roleID": 8, "isDefault": True, "isActive": True},
                        {"id": 12, "resourceID": 42, "roleID": 8, "isDefault": False, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/Roles/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 8, "name": "Service Desk", "isActive": True},
                        {"id": 9, "name": "Field Technician", "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )
        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def get(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Fail if role lookup performs unexpected metadata GET calls."""

        raise AssertionError(f"Unexpected fake Autotask GET endpoint: {endpoint_path}")


class FakeResourceServiceDeskRoleListWithoutNamesClient(FakeResourceServiceDeskRoleListClient):
    """Fake Autotask client that blocks the optional role-name lookup."""

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return role associations but reject the optional role-name lookup."""

        if endpoint_path == "/Roles/query":
            self.post_requests.append((endpoint_path, dict(json)))
            return FakeAutotaskResponse({"message": "Access denied."}, status_code=403)

        return super().post(endpoint_path, json)


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


class FakeTicketTimeEntryContextClient:
    """Fake Autotask client that returns ticket fields used for TimeEntries."""

    def __init__(self) -> None:
        """Initialize captured ticket context query payloads."""

        # posted_payload stores the exact Tickets/query body sent by the provider.
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return a ticket with assigned role and billing code context."""

        assert endpoint_path == "/Tickets/query"
        self.posted_payload = dict(json)
        return FakeAutotaskResponse(
            {
                "items": [
                    {
                        "id": 123456,
                        "ticketNumber": "T20260616.0001",
                        "assignedResourceroleID": 8,
                        "assignedResourceID": 42,
                        "billingCodeID": 24746620,
                    }
                ],
                "pageDetails": {},
            }
        )


class FakeTicketMissingRoleTimeEntryContextClient:
    """Fake Autotask client for tickets that lack assigned role context."""

    def __init__(self) -> None:
        """Initialize captured query payloads for role fallback assertions."""

        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return a ticket without role context, then a resource default role."""

        self.post_requests.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 10, "resourceID": 42, "roleID": 7, "isDefault": False, "isActive": True},
                        {"id": 11, "resourceID": 42, "roleID": 8, "isDefault": True, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")


class FakeTicketAssignedResourceRoleTimeEntryContextClient:
    """Fake client for tickets with an assigned resource but no assigned role."""

    def __init__(self) -> None:
        """Initialize captured query payloads for ticket-assigned resource assertions."""

        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket context, then the ticket-assigned resource role."""

        self.post_requests.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "assignedResourceID": 99,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            assert json["filter"][0]["value"] == 99
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 21, "resourceID": 99, "roleID": 12, "isDefault": True, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")


class FakeTicketSecondaryResourceRoleTimeEntryContextClient:
    """Fake client for tickets where the submitter is a secondary resource."""

    def __init__(self) -> None:
        """Initialize captured query payloads for secondary-resource assertions."""

        self.post_requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket context, then the submitter's ticket-specific role."""

        self.post_requests.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "assignedResourceID": 99,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            assert json["filter"][0]["value"] == 123456
            assert json["filter"][1]["value"] == 42
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 31, "ticketID": 123456, "resourceID": 42, "roleID": 15},
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")


class FakeTicketAssignedResourceSingleRoleTimeEntryContextClient:
    """Fake client for a ticket-assigned resource with one non-default role."""

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket context, then one active role without a default flag."""

        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "assignedResourceID": 99,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            assert json["filter"][0]["value"] == 99
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 21, "resourceID": 99, "roleID": 12, "isDefault": False, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")


class FakeConfiguredDefaultRoleClient:
    """Fake client for tickets where only the configured user default role is usable."""

    def __init__(self) -> None:
        """Initialize captured operations and the TimeEntries payload."""

        self.post_requests: list[tuple[str, dict[str, Any]]] = []
        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return missing ticket role context or capture TimeEntries create."""

        self.post_requests.append((endpoint_path, dict(json)))
        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            raise AssertionError("Configured default role should avoid ambiguous ResourceServiceDeskRoles fallback.")
        if endpoint_path == "/TimeEntries":
            self.posted_payload = dict(json)
            return FakeAutotaskResponse({"itemId": 987654})

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture required submission-time ticket status updates."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets":
            return FakeAutotaskResponse({})

        raise AssertionError(f"Unexpected fake Autotask PATCH endpoint: {endpoint_path}")


class FakeTimeEntryUpdateClient:
    """Fake Autotask client that captures the TimeEntries update payload."""

    def __init__(self) -> None:
        """Initialize payload capture used by the TimeEntries update test."""

        # patched_payload stores the exact JSON body sent to the fake endpoint.
        self.patched_payload: dict[str, Any] | None = None

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture one TimeEntries PATCH and return a successful response."""

        assert endpoint_path == "/TimeEntries"
        self.patched_payload = dict(json)
        return FakeAutotaskResponse({})


class FakeSubmittedCompleteTimeEntryUpdateClient:
    """Fake client for editing a submitted entry whose ticket starts Complete."""

    def __init__(self) -> None:
        """Initialize operation captures for sequencing assertions."""

        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.patched_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return the ticket ID needed for status updates."""

        assert endpoint_path == "/Tickets/query"
        self.operations.append((endpoint_path, dict(json)))
        return FakeAutotaskResponse(
            {
                "items": [{"id": 123456, "ticketNumber": "T20260616.0001"}],
                "pageDetails": {},
            }
        )

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture ticket and time-entry patch order."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/TimeEntries":
            self.patched_payload = dict(json)
        elif endpoint_path != "/Tickets":
            raise AssertionError(f"Unexpected fake Autotask PATCH endpoint: {endpoint_path}")
        return FakeAutotaskResponse({})


class FakeCompleteSubmissionClient:
    """Fake client for complete-status submission sequencing."""

    def __init__(self) -> None:
        """Initialize operation captures for create sequencing assertions."""

        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket context or capture TimeEntries create payload."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260616.0001",
                            "assignedResourceroleID": 8,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TimeEntries":
            self.posted_payload = dict(json)
            return FakeAutotaskResponse({"itemId": 987654})

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture ticket status patch payloads."""

        assert endpoint_path == "/Tickets"
        self.operations.append((endpoint_path, dict(json)))
        return FakeAutotaskResponse({})


class FakeMissingTicketRoleSubmissionClient:
    """Fake client for submission when the selected ticket has no assigned role."""

    def __init__(self) -> None:
        """Initialize operation captures for fallback role assertions."""

        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket/resource role context or capture TimeEntries create."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 11, "resourceID": 42, "roleID": 8, "isDefault": True, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TimeEntries":
            self.posted_payload = dict(json)
            return FakeAutotaskResponse({"itemId": 987654})

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture ticket status patch payloads."""

        assert endpoint_path == "/Tickets"
        self.operations.append((endpoint_path, dict(json)))
        return FakeAutotaskResponse({})


class FakeTicketSecondaryResourceRoleSubmissionClient:
    """Fake client for submission that resolves role from ticket secondary resource."""

    def __init__(self) -> None:
        """Initialize operation captures for secondary-resource assertions."""

        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket/secondary role context or capture TimeEntries create."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "assignedResourceID": 99,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            assert json["filter"][0]["value"] == 123456
            assert json["filter"][1]["value"] == 42
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 31, "ticketID": 123456, "resourceID": 42, "roleID": 15},
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TimeEntries":
            self.posted_payload = dict(json)
            return FakeAutotaskResponse({"itemId": 987654})

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture ticket status patch payloads."""

        assert endpoint_path == "/Tickets"
        self.operations.append((endpoint_path, dict(json)))
        return FakeAutotaskResponse({})


class FakeTicketAssignedResourceRoleSubmissionClient:
    """Fake client for submission that resolves role from ticket assigned resource."""

    def __init__(self) -> None:
        """Initialize operation captures for ticket-assigned resource assertions."""

        self.operations: list[tuple[str, dict[str, Any] | None]] = []
        self.posted_payload: dict[str, Any] | None = None

    def post(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Return ticket/resource role context or capture TimeEntries create."""

        self.operations.append((endpoint_path, dict(json)))
        if endpoint_path == "/Tickets/query":
            return FakeAutotaskResponse(
                {
                    "items": [
                        {
                            "id": 123456,
                            "ticketNumber": "T20260621.0001",
                            "assignedResourceroleID": None,
                            "assignedResourceID": 99,
                            "billingCodeID": 24746620,
                        }
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TicketSecondaryResources/query":
            return FakeAutotaskResponse({"items": [], "pageDetails": {}})
        if endpoint_path == "/ResourceServiceDeskRoles/query":
            assert json["filter"][0]["value"] == 99
            return FakeAutotaskResponse(
                {
                    "items": [
                        {"id": 21, "resourceID": 99, "roleID": 12, "isDefault": True, "isActive": True},
                    ],
                    "pageDetails": {},
                }
            )
        if endpoint_path == "/TimeEntries":
            self.posted_payload = dict(json)
            return FakeAutotaskResponse({"itemId": 987654})

        raise AssertionError(f"Unexpected fake Autotask POST endpoint: {endpoint_path}")

    def patch(self, endpoint_path: str, json: dict[str, Any]) -> FakeAutotaskResponse:
        """Capture ticket status patch payloads."""

        assert endpoint_path == "/Tickets"
        self.operations.append((endpoint_path, dict(json)))
        return FakeAutotaskResponse({})


class FakeTimeEntryDeleteClient:
    """Fake Autotask client that captures the TimeEntries delete endpoint."""

    def __init__(self) -> None:
        """Initialize endpoint capture used by the TimeEntries delete test."""

        # deleted_endpoint stores the exact REST path used for the delete call.
        self.deleted_endpoint: str | None = None

    def delete(self, endpoint_path: str) -> FakeAutotaskResponse:
        """Capture one TimeEntries DELETE request and return success."""

        self.deleted_endpoint = endpoint_path
        return FakeAutotaskResponse({})


class FakeAutotaskClientContext:
    """Context manager that lets provider tests inject a fake Autotask client."""

    def __init__(self, client: object) -> None:
        """Store the fake client returned from ``with provider._client()``."""

        self.client = client

    def __enter__(self) -> object:
        """Return the fake client for the provider operation."""

        return self.client

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        """Do not suppress provider exceptions."""

        return False


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
    _TICKET_SOURCE_CACHE.clear()
    _OPEN_TICKET_SELECTION_CACHE.clear()
    _RESOURCE_SEARCH_CACHE.clear()
    _SERVICE_CALL_SELECTION_CACHE.clear()


def test_live_provider_updates_cached_autotask_health_from_api_results() -> None:
    """Autotask API failures should alert until a later API call succeeds."""

    provider = _live_test_provider()

    with pytest.raises(httpx.ConnectError):
        provider._api_request(
            FakeTransportFailureClient(),
            "POST",
            "/Companies/query",
            "Autotask company lookup",
            json={"MaxRecords": 1},
        )

    transport_health = system_health.cached_autotask_health()
    assert transport_health.available is False
    assert transport_health.operation == "Autotask company lookup"
    assert transport_health.summary == "Autotask company lookup could not reach the Autotask API."

    with pytest.raises(AutotaskSubmissionError):
        provider._raise_for_safe_response(
            FakeAutotaskResponse({"errors": ["Permission denied."]}, status_code=500),
            "Autotask ticket lookup",
        )

    failed_response_health = system_health.cached_autotask_health()
    assert failed_response_health.available is False
    assert failed_response_health.operation == "Autotask ticket lookup"
    assert "Autotask HTTP 500" in failed_response_health.summary

    provider._api_request(
        FakeSuccessfulApiClient(),
        "GET",
        "/Tickets/entityInformation/fields/status",
        "Autotask status metadata lookup",
    )

    recovered_health = system_health.cached_autotask_health()
    assert recovered_health.available is True
    assert recovered_health.operation == "Autotask status metadata lookup"


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
    assert first_lookup[0].detected_work_location == WorkLocation.REMOTE
    assert first_lookup[0].work_location_label == "Remote"
    assert second_lookup == first_lookup
    assert fake_client.company_query_count == 1
    assert fake_client.ticket_query_count == 1
    assert fake_client.status_lookup_count == 1
    assert fake_client.source_lookup_count == 1


def test_live_ticket_notes_lookup_uses_selected_ticket_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ticket notes should be read through the selected ticket ID with bounded fields."""

    provider = _live_test_provider()
    fake_client = FakeTicketNotesLookupClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake client while matching the provider client signature."""

        # timeout_seconds is accepted so the fake matches LiveAutotaskProvider._client.
        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    notes = provider.list_ticket_notes("T20260616.0001", resource_id=42)

    assert [endpoint_path for endpoint_path, _payload in fake_client.post_requests] == [
        "/Tickets/query",
        "/TicketNotes/query",
    ]
    assert len(notes) == 2
    assert notes[0].note_id == 91002
    assert notes[0].title == "Technician update"
    assert notes[0].description == "Technician confirmed WAN status before dispatch."
    assert notes[0].created_at_utc == datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    assert notes[0].updated_at_utc is None
    assert notes[0].publish == 2
    assert notes[1].note_id == 91001
    assert notes[1].created_at_utc == datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    assert notes[1].updated_at_utc == datetime(2026, 6, 16, 12, 30, tzinfo=UTC)


def test_todays_service_call_lookup_uses_resource_assignment_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Today's service calls should be resolved through ticket-resource assignments."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeServiceCallLookupClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake service-call client while matching the provider signature."""

        # timeout_seconds is accepted so the fake matches LiveAutotaskProvider._client.
        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    current_time_utc = datetime(2026, 6, 16, 15, 30, tzinfo=UTC)
    first_lookup = provider.list_todays_service_calls_for_resource(resource_id=1, current_time_utc=current_time_utc)
    second_lookup = provider.list_todays_service_calls_for_resource(resource_id=1, current_time_utc=current_time_utc)

    assert len(first_lookup) == 1
    service_call_option = first_lookup[0]
    assert service_call_option.service_call_id == 7001
    assert service_call_option.service_call_ticket_id == 8001
    assert service_call_option.service_call_name == "Firewall replacement"
    assert service_call_option.work_location_label == "Remote"
    assert service_call_option.detected_work_location == WorkLocation.REMOTE
    assert service_call_option.ticket_number == "T20260616.0007"
    assert service_call_option.ticket_title == "Firewall replacement"
    assert service_call_option.ticket_description == "Replace firewall and verify VPN."
    assert service_call_option.ticket_status_label == "In Progress"
    assert service_call_option.client_name == "Acme Services"
    assert service_call_option.autotask_company_id == 1001
    assert service_call_option.start_datetime_utc == datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    assert service_call_option.end_datetime_utc == datetime(2026, 6, 16, 14, 0, tzinfo=UTC)
    assert second_lookup == first_lookup
    assert fake_client.status_lookup_count == 1
    assert fake_client.source_lookup_count == 1
    assert [endpoint_path for endpoint_path, _payload in fake_client.post_requests] == [
        "/ServiceCalls/query",
        "/ServiceCallTickets/query",
        "/ServiceCallTicketResources/query",
        "/Tickets/query",
        "/Companies/query",
    ]


def test_resource_lookup_uses_name_filters_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Managed-user resource lookup should search first/last names and cache the result."""

    _clear_autotask_lookup_caches()
    provider = _live_test_provider()
    fake_client = FakeResourceLookupClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake resource client while matching the provider signature."""

        # timeout_seconds is accepted so the fake matches LiveAutotaskProvider._client.
        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    first_lookup = provider.search_resources("Joe Blow")
    second_lookup = provider.search_resources("Joe Blow")

    assert len(first_lookup) == 1
    assert first_lookup[0].resource_id == 42
    assert first_lookup[0].resource_name == "Blow, Joe"
    assert first_lookup[0].first_name == "Joe"
    assert first_lookup[0].last_name == "Blow"
    assert first_lookup[0].email == "joe.blow@example.test"
    assert second_lookup == first_lookup
    assert len(fake_client.post_requests) == 3
    assert fake_client.post_requests[0][1]["filter"] == [
        {"op": "contains", "field": "lastName", "value": "Blow"},
        {"op": "contains", "field": "firstName", "value": "Joe"},
    ]
    assert fake_client.post_requests[1][1]["filter"] == [
        {"op": "contains", "field": "lastName", "value": "Blow"}
    ]
    assert fake_client.post_requests[2][1]["filter"] == [
        {"op": "contains", "field": "firstName", "value": "Joe"}
    ]


def test_resource_service_desk_role_lookup_lists_active_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Managed-user setup should list active service-desk roles for a resource."""

    provider = _live_test_provider()
    fake_client = FakeResourceServiceDeskRoleListClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake role client while matching the provider signature."""

        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    role_options = provider.list_resource_service_desk_roles(42)

    assert [(role.role_id, role.name, role.label, role.is_default) for role in role_options] == [
        (8, "Service Desk", "Service Desk (ID 8, Autotask default)", True),
        (9, "Field Technician", "Field Technician (ID 9)", False),
    ]
    assert fake_client.post_requests == [
        (
            "/ResourceServiceDeskRoles/query",
            {
                "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
                "filter": [
                    {"op": "eq", "field": "resourceID", "value": 42},
                    {"op": "eq", "field": "isActive", "value": True},
                ],
                "MaxRecords": 50,
            },
        ),
        (
            "/Roles/query",
            {
                "IncludeFields": ["id", "name", "isActive"],
                "filter": [
                    {"op": "in", "field": "id", "value": [9, 8]},
                ],
                "MaxRecords": 2,
            },
        ),
    ]


def test_resource_service_desk_role_lookup_falls_back_without_role_name_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Role lookup should still work when Autotask blocks the optional Roles query."""

    provider = _live_test_provider()
    fake_client = FakeResourceServiceDeskRoleListWithoutNamesClient()

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeConnectivityContext:
        """Return one fake role client while matching the provider signature."""

        assert timeout_seconds == 30.0
        return FakeConnectivityContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    role_options = provider.list_resource_service_desk_roles(42)

    assert [(role.role_id, role.name, role.label, role.is_default) for role in role_options] == [
        (8, None, "Role 8 (Autotask default)", True),
        (9, None, "Role 9", False),
    ]


def test_debug_connectivity_check_runs_fresh_provider_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The debug Autotask test should run the provider check when requested."""

    _clear_autotask_lookup_caches()
    fake_provider = FakeConnectivityProvider()
    provider_settings = _live_test_provider().application_settings

    monkeypatch.setattr("job_logger.services.autotask.get_autotask_provider", lambda application_settings: fake_provider)

    first_debug_result = run_autotask_connectivity(provider_settings)
    second_debug_result = run_autotask_connectivity(provider_settings)

    assert first_debug_result.available is True
    assert second_debug_result.available is True
    assert fake_provider.check_count == 2


def test_autotask_headers_do_not_send_impersonation_resource_id() -> None:
    """Autotask calls should not use the optional impersonation header."""

    provider = _live_test_provider()
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


def test_ticket_time_entry_context_uses_ticket_role_and_billing_code() -> None:
    """Ticket submission should read the role and billing code from the selected ticket."""

    provider = _live_test_provider()
    fake_client = FakeTicketTimeEntryContextClient()

    ticket_context = provider._query_ticket_time_entry_context(fake_client, "T20260616.0001", resource_id=42)

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 8
    assert ticket_context.role_id_source == "ticket.assignedResourceroleID"
    assert ticket_context.assigned_resource_id == 42
    assert ticket_context.billing_code_id == 24746620
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["IncludeFields"] == [
        "id",
        "ticketNumber",
        "assignedResourceroleID",
        "assignedResourceID",
        "billingCodeID",
    ]


def test_ticket_time_entry_context_falls_back_to_resource_default_role() -> None:
    """Tickets missing assigned role context should use the submitter's default role."""

    provider = _live_test_provider()
    fake_client = FakeTicketMissingRoleTimeEntryContextClient()

    ticket_context = provider._query_ticket_time_entry_context(fake_client, "T20260621.0001", resource_id=42)

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 8
    assert ticket_context.role_id_source == "managed_web_user.autotask_resource_id.ResourceServiceDeskRoles.default.roleID"
    assert ticket_context.assigned_resource_id is None
    assert ticket_context.billing_code_id == 24746620
    assert fake_client.post_requests == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        (
            "/ResourceServiceDeskRoles/query",
            {
                "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
                "filter": [
                    {"op": "eq", "field": "resourceID", "value": 42},
                    {"op": "eq", "field": "isActive", "value": True},
                ],
                "MaxRecords": 50,
            },
        ),
    ]


def test_ticket_time_entry_context_uses_matching_secondary_resource_role() -> None:
    """A submitter assigned as a secondary resource should use that ticket role."""

    provider = _live_test_provider()
    fake_client = FakeTicketSecondaryResourceRoleTimeEntryContextClient()

    ticket_context = provider._query_ticket_time_entry_context(fake_client, "T20260621.0001", resource_id=42)

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 15
    assert ticket_context.role_id_source == "ticket.secondaryResource.roleID"
    assert ticket_context.assigned_resource_id == 99
    assert fake_client.post_requests == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
    ]


def test_ticket_time_entry_context_uses_ticket_assigned_resource_role_when_ticket_role_missing() -> None:
    """Tickets with only assignedResourceID should use that resource's role context."""

    provider = _live_test_provider()
    fake_client = FakeTicketAssignedResourceRoleTimeEntryContextClient()

    ticket_context = provider._query_ticket_time_entry_context(fake_client, "T20260621.0001", resource_id=42)

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 12
    assert ticket_context.role_id_source == "ticket.assignedResourceID.ResourceServiceDeskRoles.default.roleID"
    assert ticket_context.assigned_resource_id == 99
    assert fake_client.post_requests == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        (
            "/ResourceServiceDeskRoles/query",
            {
                "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
                "filter": [
                    {"op": "eq", "field": "resourceID", "value": 99},
                    {"op": "eq", "field": "isActive", "value": True},
                ],
                "MaxRecords": 50,
            },
        ),
    ]


def test_ticket_time_entry_context_uses_single_active_ticket_assigned_resource_role() -> None:
    """A single active role is safe when Autotask does not mark a default."""

    provider = _live_test_provider()
    fake_client = FakeTicketAssignedResourceSingleRoleTimeEntryContextClient()

    ticket_context = provider._query_ticket_time_entry_context(fake_client, "T20260621.0001", resource_id=42)

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 12
    assert ticket_context.role_id_source == "ticket.assignedResourceID.ResourceServiceDeskRoles.singleActive.roleID"
    assert ticket_context.assigned_resource_id == 99


def test_ticket_time_entry_context_uses_configured_default_role_when_autotask_roles_are_ambiguous() -> None:
    """A configured user role should be usable when ticket-derived role context is absent."""

    provider = _live_test_provider()
    fake_client = FakeConfiguredDefaultRoleClient()

    ticket_context = provider._query_ticket_time_entry_context(
        fake_client,
        "T20260621.0001",
        resource_id=42,
        default_service_desk_role_id=77,
    )

    assert ticket_context.ticket_id == 123456
    assert ticket_context.role_id == 77
    assert ticket_context.role_id_source == "managed_web_user.autotask_default_service_desk_role_id"
    assert ticket_context.assigned_resource_id is None
    assert fake_client.post_requests == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
    ]


def test_time_entry_creation_uses_ticket_role_and_inherits_billing_code() -> None:
    """Ticket TimeEntries should use ticket role and let Autotask inherit billing code."""

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

    external_id = provider._create_time_entry(fake_client, job, ticket_id=123456, resource_id=1, role_id=8)

    assert external_id == "987654"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 1
    assert fake_client.posted_payload["roleID"] == 8
    assert fake_client.posted_payload["timeEntryType"] == 2
    assert fake_client.posted_payload["summaryNotes"] == "Remote. Payload must not include allocation code."
    assert "billingCodeID" not in fake_client.posted_payload


def test_complete_submission_updates_ticket_status_after_time_entry_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """Final Complete status should be applied after TimeEntries creation."""

    provider = _live_test_provider()
    fake_client = FakeCompleteSubmissionClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="complete-submit-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Complete after submitted time.",
        description_text="Complete after submitted time.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=1)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["ticketStatusPreUpdate"] == "in_progress"
    assert result.request_snapshot["ticketStatusPostUpdate"] == "complete"
    assert fake_client.posted_payload is not None
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260616.0001"}],
                "MaxRecords": 1,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
        ("/Tickets", {"id": 123456, "status": 5}),
    ]


def test_submission_updates_ticket_status_before_and_after_complete_time_entry_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TimeEntries submission should sync the selected app ticket status."""

    provider = _live_test_provider()
    fake_client = FakeCompleteSubmissionClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="complete-submit-without-ticket-status-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Create time and change ticket status.",
        description_text="Create time and change ticket status.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=1)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["ticketStatusUpdatePolicy"] == "required_on_submit"
    assert result.request_snapshot["ticketStatusUpdateAttempted"] is True
    assert result.request_snapshot["ticketStatusPreUpdate"] == "in_progress"
    assert result.request_snapshot["ticketStatusPostUpdate"] == "complete"
    assert fake_client.posted_payload is not None
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260616.0001"}],
                "MaxRecords": 1,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
        ("/Tickets", {"id": 123456, "status": 5}),
    ]


def test_submission_fails_when_selected_ticket_status_id_is_not_configured() -> None:
    """Submitting should not create time when the selected status cannot sync."""

    provider = _live_test_provider()
    provider = LiveAutotaskProvider(replace(provider.application_settings, autotask_status_complete_id=None))
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="complete-submit-missing-status-id-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Missing status ID should fail.",
        description_text="Missing status ID should fail.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    result = provider.submit_job(job, resource_id=1)

    assert result.succeeded is False
    assert result.external_id is None
    assert result.safe_error == "Autotask status ID for Complete is not configured."
    assert result.request_snapshot["ticketStatusUpdatePolicy"] == "required_on_submit"
    assert result.request_snapshot["ticketStatusUpdateAttempted"] is False


def test_submission_uses_resource_default_role_when_ticket_role_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submitting time should not fail early when a ticket omits assigned role."""

    provider = _live_test_provider()
    fake_client = FakeMissingTicketRoleSubmissionClient()
    rounded_start_utc = datetime(2026, 6, 21, 13, 0, tzinfo=UTC)
    job = Job(
        id="missing-role-submit-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260621.0001",
        ticket_status=TicketStatus.IN_PROGRESS,
        summary_notes="Created time with fallback role.",
        description_text="Created time with fallback role.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=42)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["roleID"] == 8
    assert result.request_snapshot["roleIDSource"] == "managed_web_user.autotask_resource_id.ResourceServiceDeskRoles.default.roleID"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 42
    assert fake_client.posted_payload["roleID"] == 8
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        (
            "/ResourceServiceDeskRoles/query",
            {
                "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
                "filter": [
                    {"op": "eq", "field": "resourceID", "value": 42},
                    {"op": "eq", "field": "isActive", "value": True},
                ],
                "MaxRecords": 50,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
    ]


def test_submission_uses_configured_default_role_when_autotask_roles_are_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submitting time can use the web user's configured role fallback."""

    provider = _live_test_provider()
    fake_client = FakeConfiguredDefaultRoleClient()
    rounded_start_utc = datetime(2026, 6, 21, 13, 0, tzinfo=UTC)
    job = Job(
        id="configured-role-submit-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260621.0001",
        ticket_status=TicketStatus.IN_PROGRESS,
        summary_notes="Created time with configured default role.",
        description_text="Created time with configured default role.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=42, default_service_desk_role_id=77)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["configuredDefaultServiceDeskRoleID"] == 77
    assert result.request_snapshot["roleID"] == 77
    assert result.request_snapshot["roleIDSource"] == "managed_web_user.autotask_default_service_desk_role_id"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 42
    assert fake_client.posted_payload["roleID"] == 77
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
    ]


def test_submission_uses_matching_secondary_resource_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submitting user secondary-resource roles should avoid generic role guessing."""

    provider = _live_test_provider()
    fake_client = FakeTicketSecondaryResourceRoleSubmissionClient()
    rounded_start_utc = datetime(2026, 6, 21, 13, 0, tzinfo=UTC)
    job = Job(
        id="secondary-resource-role-submit-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260621.0001",
        ticket_status=TicketStatus.IN_PROGRESS,
        summary_notes="Created time with ticket secondary resource role.",
        description_text="Created time with ticket secondary resource role.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=42)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["resourceID"] == 42
    assert result.request_snapshot["ticketAssignedResourceID"] == 99
    assert result.request_snapshot["roleID"] == 15
    assert result.request_snapshot["roleIDSource"] == "ticket.secondaryResource.roleID"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 42
    assert fake_client.posted_payload["roleID"] == 15
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
    ]


def test_submission_uses_ticket_assigned_resource_role_when_ticket_role_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ticket assignedResourceID can supply role context without changing submitter resource."""

    provider = _live_test_provider()
    fake_client = FakeTicketAssignedResourceRoleSubmissionClient()
    rounded_start_utc = datetime(2026, 6, 21, 13, 0, tzinfo=UTC)
    job = Job(
        id="assigned-resource-role-submit-test",
        status=JobStatus.READY_FOR_REVIEW,
        ticket_number="T20260621.0001",
        ticket_status=TicketStatus.IN_PROGRESS,
        summary_notes="Created time with ticket assigned resource role.",
        description_text="Created time with ticket assigned resource role.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=30),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=30),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.submit_job(job, resource_id=42)

    assert result.succeeded is True
    assert result.external_id == "987654"
    assert result.request_snapshot["resourceID"] == 42
    assert result.request_snapshot["ticketAssignedResourceID"] == 99
    assert result.request_snapshot["roleID"] == 12
    assert result.request_snapshot["roleIDSource"] == "ticket.assignedResourceID.ResourceServiceDeskRoles.default.roleID"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["ticketID"] == 123456
    assert fake_client.posted_payload["resourceID"] == 42
    assert fake_client.posted_payload["roleID"] == 12
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber", "assignedResourceroleID", "assignedResourceID", "billingCodeID"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260621.0001"}],
                "MaxRecords": 1,
            },
        ),
        (
            "/TicketSecondaryResources/query",
            {
                "IncludeFields": ["id", "ticketID", "resourceID", "roleID"],
                "filter": [
                    {"op": "eq", "field": "ticketID", "value": 123456},
                    {"op": "eq", "field": "resourceID", "value": 42},
                ],
                "MaxRecords": 50,
            },
        ),
        (
            "/ResourceServiceDeskRoles/query",
            {
                "IncludeFields": ["id", "resourceID", "roleID", "isDefault", "isActive"],
                "filter": [
                    {"op": "eq", "field": "resourceID", "value": 99},
                    {"op": "eq", "field": "isActive", "value": True},
                ],
                "MaxRecords": 50,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.posted_payload),
    ]


def test_time_entry_update_patches_existing_entry_fields_only() -> None:
    """Submitted entry edits must patch the existing TimeEntries row."""

    provider = _live_test_provider()
    fake_client = FakeTimeEntryUpdateClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="time-entry-update-test",
        status=JobStatus.SUBMITTED,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.FOLLOW_UP,
        summary_notes="Updated the submitted entry notes.",
        description_text="Updated the submitted entry notes.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=45),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=45),
    )

    provider._update_time_entry(fake_client, job, external_id="987654")

    assert fake_client.patched_payload is not None
    assert fake_client.patched_payload["id"] == 987654
    assert fake_client.patched_payload["startDateTime"] == "2026-06-16T13:00:00Z"
    assert fake_client.patched_payload["endDateTime"] == "2026-06-16T13:45:00Z"
    assert fake_client.patched_payload["hoursWorked"] == 0.75
    assert fake_client.patched_payload["summaryNotes"] == "Remote. Updated the submitted entry notes."
    assert "ticketID" not in fake_client.patched_payload
    assert "resourceID" not in fake_client.patched_payload
    assert "roleID" not in fake_client.patched_payload
    assert "billingCodeID" not in fake_client.patched_payload


def test_live_time_entry_update_reopens_complete_ticket_before_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Submitted-entry edits reopen Complete tickets before patching TimeEntries."""

    provider = _live_test_provider()
    fake_client = FakeSubmittedCompleteTimeEntryUpdateClient()
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="time-entry-update-without-ticket-status-test",
        status=JobStatus.SUBMITTED,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.COMPLETE,
        summary_notes="Updated submitted notes without changing ticket status.",
        description_text="Updated submitted notes without changing ticket status.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=45),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=45),
    )

    def fake_client_context(timeout_seconds: float = 30.0) -> FakeAutotaskClientContext:
        """Return the fake client while matching the provider client signature."""

        assert timeout_seconds == 30.0
        return FakeAutotaskClientContext(fake_client)

    monkeypatch.setattr(provider, "_client", fake_client_context)

    result = provider.update_time_entry(
        job,
        external_id="987654",
        resource_id=1,
        previous_ticket_status=TicketStatus.COMPLETE,
    )

    assert result.succeeded is True
    assert result.safe_error is None
    assert result.request_snapshot["ticketStatusUpdateRequested"] is True
    assert result.request_snapshot["ticketStatusUpdateAttempted"] is True
    assert result.request_snapshot["ticketStatusPreUpdate"] == "in_progress"
    assert result.request_snapshot["ticketStatusPostUpdate"] == "complete"
    assert fake_client.patched_payload is not None
    assert fake_client.patched_payload["id"] == 987654
    assert fake_client.patched_payload["summaryNotes"] == "Remote. Updated submitted notes without changing ticket status."
    assert fake_client.operations == [
        (
            "/Tickets/query",
            {
                "IncludeFields": ["id", "ticketNumber"],
                "filter": [{"op": "eq", "field": "ticketNumber", "value": "T20260616.0001"}],
                "MaxRecords": 1,
            },
        ),
        ("/Tickets", {"id": 123456, "status": 1}),
        ("/TimeEntries", fake_client.patched_payload),
        ("/Tickets", {"id": 123456, "status": 5}),
    ]


def test_live_time_entry_update_fails_when_selected_ticket_status_id_is_not_configured() -> None:
    """Submitted-entry edits require the selected status to have a tenant picklist ID."""

    provider = _live_test_provider()
    provider = LiveAutotaskProvider(replace(provider.application_settings, autotask_status_follow_up_id=None))
    rounded_start_utc = datetime(2026, 6, 16, 13, 0, tzinfo=UTC)
    job = Job(
        id="time-entry-update-missing-status-id-test",
        status=JobStatus.SUBMITTED,
        ticket_number="T20260616.0001",
        ticket_status=TicketStatus.FOLLOW_UP,
        summary_notes="Missing edit status ID should fail.",
        description_text="Missing edit status ID should fail.",
        raw_start_utc=rounded_start_utc,
        raw_end_utc=rounded_start_utc + timedelta(minutes=45),
        rounded_start_utc=rounded_start_utc,
        rounded_end_utc=rounded_start_utc + timedelta(minutes=45),
    )

    result = provider.update_time_entry(
        job,
        external_id="987654",
        resource_id=1,
        previous_ticket_status=TicketStatus.IN_PROGRESS,
    )

    assert result.succeeded is False
    assert result.external_id == "987654"
    assert result.safe_error == "Autotask status ID for Follow up is not configured."
    assert result.request_snapshot["ticketStatusUpdatePolicy"] == "required_on_edit"
    assert result.request_snapshot["ticketStatusUpdateAttempted"] is True


def test_time_entry_delete_uses_existing_entry_endpoint() -> None:
    """Submitted entry deletes must target the existing TimeEntries row."""

    provider = _live_test_provider()
    fake_client = FakeTimeEntryDeleteClient()

    provider._delete_time_entry(fake_client, external_id="987654")

    assert fake_client.deleted_endpoint == "/TimeEntries/987654"


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

    external_id = provider._create_time_entry(fake_client, job, ticket_id=123456, resource_id=1, role_id=8)

    assert external_id == "987654"
    assert fake_client.posted_payload is not None
    assert fake_client.posted_payload["summaryNotes"] == "On-Site. replaced the router and verified service."


def test_summary_prefix_parser_accepts_new_and_legacy_work_location_formats() -> None:
    """Review parsing should accept the new period prefix and older visible prefixes."""

    assert split_autotask_summary_notes("Remote. Replaced the router.", WorkLocation.ON_SITE) == (
        WorkLocation.REMOTE,
        "Replaced the router.",
    )
    assert split_autotask_summary_notes("On-Site replaced the access point.", WorkLocation.REMOTE) == (
        WorkLocation.ON_SITE,
        "replaced the access point.",
    )
    assert split_autotask_summary_notes("Remote: Verified backups.", WorkLocation.ON_SITE) == (
        WorkLocation.REMOTE,
        "Verified backups.",
    )
