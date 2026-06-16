#!/usr/bin/env python3
"""Discover Autotask IDs needed by Job Logger from a local .env file.

The script performs read-only Autotask REST calls for role IDs, billing code
IDs, and ticket status picklist IDs. It intentionally avoids printing secrets,
raw request headers, or raw environment values.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


# REQUIRED_AUTOTASK_SETTINGS are the minimum values needed to authenticate
# against the Autotask REST API.
REQUIRED_AUTOTASK_SETTINGS = (
    "AUTOTASK_BASE_URL",
    "AUTOTASK_USERNAME",
    "AUTOTASK_SECRET",
    "AUTOTASK_API_INTEGRATION_CODE",
)

# STATUS_ENVIRONMENT_VARIABLES maps the local Job Logger status keys to the
# labels expected in the Autotask Tickets.status picklist metadata.
STATUS_ENVIRONMENT_VARIABLES = {
    "AUTOTASK_STATUS_IN_PROGRESS_ID": "In progress",
    "AUTOTASK_STATUS_WAITING_CUSTOMER_ID": "Waiting customer",
    "AUTOTASK_STATUS_WAITING_PARTS_ID": "Waiting parts",
    "AUTOTASK_STATUS_FOLLOW_UP_ID": "Follow up",
    "AUTOTASK_STATUS_COMPLETE_ID": "Complete",
}


@dataclass(frozen=True)
class AutotaskSettings:
    """Non-secret Autotask configuration plus secret values kept out of output."""

    # base_url is the tenant-specific Autotask REST API URL.
    base_url: str

    # username is the Autotask API user's Username (Key).
    username: str

    # secret is the Autotask API user's Secret.
    secret: str

    # api_integration_code is the Autotask API integration code header value.
    api_integration_code: str

    # impersonation_resource_id is optional and only sent when configured.
    impersonation_resource_id: str | None


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options for the discovery helper."""

    parser = argparse.ArgumentParser(
        description="Discover Autotask role, billing code, and ticket status IDs using a .env file.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the dotenv file containing Autotask settings. Default: .env",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Print inactive Autotask role, billing code, and status records too.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30",
    )
    return parser.parse_args()


def load_dotenv(dotenv_path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE pairs from a dotenv file without logging values."""

    dotenv_values: dict[str, str] = {}
    if not dotenv_path.exists():
        raise FileNotFoundError(f"Dotenv file was not found: {dotenv_path}")

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
            continue

        environment_name, environment_value = stripped_line.split("=", 1)
        environment_name = environment_name.strip()
        environment_value = environment_value.strip()
        if len(environment_value) >= 2 and environment_value[0] == environment_value[-1] and environment_value[0] in {'"', "'"}:
            environment_value = environment_value[1:-1]

        dotenv_values[environment_name] = environment_value

    return dotenv_values


def get_setting(dotenv_values: dict[str, str], setting_name: str) -> str | None:
    """Return a setting from .env first, then the process environment."""

    if setting_name in dotenv_values:
        return dotenv_values[setting_name]

    return os.getenv(setting_name)


def load_autotask_settings(dotenv_path: Path) -> AutotaskSettings:
    """Build typed Autotask settings from the configured dotenv file."""

    dotenv_values = load_dotenv(dotenv_path)
    missing_settings = [
        setting_name
        for setting_name in REQUIRED_AUTOTASK_SETTINGS
        if not get_setting(dotenv_values, setting_name)
    ]
    if missing_settings:
        raise ValueError(f"Missing required Autotask settings: {', '.join(missing_settings)}")

    return AutotaskSettings(
        base_url=str(get_setting(dotenv_values, "AUTOTASK_BASE_URL")).rstrip("/"),
        username=str(get_setting(dotenv_values, "AUTOTASK_USERNAME")),
        secret=str(get_setting(dotenv_values, "AUTOTASK_SECRET")),
        api_integration_code=str(get_setting(dotenv_values, "AUTOTASK_API_INTEGRATION_CODE")),
        impersonation_resource_id=get_setting(dotenv_values, "AUTOTASK_IMPERSONATION_RESOURCE_ID") or None,
    )


def normalize_label(label_value: object) -> str:
    """Normalize Autotask labels for case-insensitive status matching."""

    return re.sub(r"[^a-z0-9]+", "", str(label_value or "").lower())


def is_record_active(record: dict[str, Any]) -> bool:
    """Return whether an Autotask record should be considered active."""

    if "isActive" in record:
        return bool(record["isActive"])
    if "active" in record:
        return bool(record["active"])
    return True


def get_record_name(record: dict[str, Any]) -> str:
    """Return the best display name from common Autotask name fields."""

    for field_name in ("name", "Name", "description", "Description", "label", "Label"):
        field_value = record.get(field_name)
        if field_value not in (None, ""):
            return str(field_value)

    return "(no name returned)"


def get_picklist_id(record: dict[str, Any]) -> object:
    """Return an Autotask picklist value ID from common metadata fields."""

    for field_name in ("value", "Value", "id", "Id"):
        field_value = record.get(field_name)
        if field_value not in (None, ""):
            return field_value

    return None


def build_headers(settings: AutotaskSettings) -> dict[str, str]:
    """Build Autotask REST headers without exposing them in output."""

    headers = {
        "ApiIntegrationCode": settings.api_integration_code,
        "UserName": settings.username,
        "Secret": settings.secret,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if settings.impersonation_resource_id:
        headers["ImpersonationResourceId"] = settings.impersonation_resource_id

    return headers


def raise_for_autotask_error(response: httpx.Response, action_description: str) -> None:
    """Raise a short error that avoids request headers and secret values."""

    if response.status_code < 400:
        return

    response_excerpt = response.text.strip()[:1000]
    if response_excerpt:
        raise RuntimeError(f"{action_description} failed with HTTP {response.status_code}: {response_excerpt}")

    raise RuntimeError(f"{action_description} failed with HTTP {response.status_code}.")


def query_entity_records(client: httpx.Client, entity_name: str) -> list[dict[str, Any]]:
    """Query all records for a simple Autotask entity using id >= 0."""

    query_payload = {"filter": [{"op": "gte", "field": "id", "value": 0}]}
    response = client.post(f"/{entity_name}/query", json=query_payload)
    raise_for_autotask_error(response, f"{entity_name}/query")

    response_payload = response.json()
    records = response_payload.get("items") or response_payload.get("Item") or []
    if not isinstance(records, list):
        raise RuntimeError(f"{entity_name}/query did not return a record list.")

    return [record for record in records if isinstance(record, dict)]


def query_ticket_status_values(client: httpx.Client) -> list[dict[str, Any]]:
    """Return the Tickets.status picklist values from Autotask metadata."""

    response = client.get("/Tickets/entityInformation/fields/status")
    if response.status_code == 404:
        response = client.get("/Tickets/entityInformation/fields")

    raise_for_autotask_error(response, "Tickets.status metadata query")
    response_payload = response.json()

    # Some tenants return a single field for /fields/status, while others return
    # a list of fields from the fallback endpoint.
    status_field: dict[str, Any] | None = None
    if isinstance(response_payload, dict) and "picklistValues" in response_payload:
        status_field = response_payload
    else:
        fields = response_payload.get("fields") if isinstance(response_payload, dict) else response_payload
        if isinstance(fields, list):
            for field_record in fields:
                if isinstance(field_record, dict) and normalize_label(field_record.get("name")) == "status":
                    status_field = field_record
                    break

    if status_field is None:
        raise RuntimeError("Could not find Tickets.status field metadata.")

    picklist_values = status_field.get("picklistValues") or status_field.get("PicklistValues") or []
    if not isinstance(picklist_values, list):
        raise RuntimeError("Tickets.status metadata did not include picklistValues.")

    return [record for record in picklist_values if isinstance(record, dict)]


def print_zone_information(client: httpx.Client, settings: AutotaskSettings) -> None:
    """Print non-secret Autotask zone information for troubleshooting."""

    response = client.get("/zoneInformation", params={"user": settings.username})
    raise_for_autotask_error(response, "zoneInformation")

    zone_payload = response.json()
    configured_url = urlparse(settings.base_url)
    print("Autotask Zone")
    print("-------------")
    print(f"configured_host={configured_url.netloc}")
    print(f"zone_name={zone_payload.get('zoneName')}")
    print(f"zone_url={zone_payload.get('url')}")
    print()


def print_role_records(role_records: list[dict[str, Any]], *, include_inactive: bool) -> None:
    """Print Autotask role IDs and names."""

    print("Role IDs")
    print("--------")
    visible_records = [record for record in role_records if include_inactive or is_record_active(record)]
    for record in sorted(visible_records, key=lambda item: str(item.get("name") or item.get("id"))):
        active_text = f" active={is_record_active(record)}"
        print(f"id={record.get('id')} name={get_record_name(record)}{active_text}")
    print()


def print_billing_code_records(billing_code_records: list[dict[str, Any]], *, include_inactive: bool) -> None:
    """Print Autotask billing code IDs, names, and useful non-secret fields."""

    print("Billing Code IDs")
    print("----------------")
    visible_records = [record for record in billing_code_records if include_inactive or is_record_active(record)]
    for record in sorted(visible_records, key=lambda item: str(item.get("name") or item.get("id"))):
        useful_fields = []
        for field_name in ("externalNumber", "unitCost", "unitPrice", "useType"):
            if record.get(field_name) not in (None, ""):
                useful_fields.append(f"{field_name}={record.get(field_name)}")

        useful_text = "" if not useful_fields else " " + " ".join(useful_fields)
        active_text = f" active={is_record_active(record)}"
        print(f"id={record.get('id')} name={get_record_name(record)}{active_text}{useful_text}")
    print()


def print_ticket_status_records(status_records: list[dict[str, Any]], *, include_inactive: bool) -> None:
    """Print status mappings and all visible Autotask ticket status values."""

    print("Ticket Status IDs For .env")
    print("--------------------------")
    normalized_status_records = {
        normalize_label(get_record_name(record)): record
        for record in status_records
        if include_inactive or is_record_active(record)
    }

    for environment_variable_name, status_label in STATUS_ENVIRONMENT_VARIABLES.items():
        status_record = normalized_status_records.get(normalize_label(status_label))
        if status_record is None:
            print(f"# {environment_variable_name}=not-found")
            continue

        print(f"{environment_variable_name}={get_picklist_id(status_record)}")
    print()

    print("All Ticket Status Values")
    print("------------------------")
    for record in status_records:
        if not include_inactive and not is_record_active(record):
            continue

        print(f"id={get_picklist_id(record)} label={get_record_name(record)} active={is_record_active(record)}")


def main() -> int:
    """Run all read-only Autotask discovery queries."""

    arguments = parse_arguments()
    dotenv_path = Path(arguments.env_file)
    settings = load_autotask_settings(dotenv_path)

    with httpx.Client(base_url=settings.base_url, headers=build_headers(settings), timeout=arguments.timeout) as client:
        print_zone_information(client, settings)
        print_role_records(query_entity_records(client, "Roles"), include_inactive=arguments.include_inactive)
        print_billing_code_records(query_entity_records(client, "BillingCodes"), include_inactive=arguments.include_inactive)
        print_ticket_status_records(query_ticket_status_values(client), include_inactive=arguments.include_inactive)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Autotask discovery failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
