"""Tests for managed web-user authentication and administration."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from job_logger import database
from job_logger.enums import JobStatus, TranscriptionStatus, WorkLocation
from job_logger.models import AuditEvent, Job, WebAuthnCredential, WebUser
from job_logger.services.users import WebUserError, hash_password, suggested_username_from_full_name
from job_logger.ui import static_asset_version
from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token, login_as, login_as_super_admin, login_as_web_user


def _seed_unowned_job() -> str:
    """Create a legacy-style job without a web-user owner."""

    created_at_utc = datetime(2026, 6, 20, 13, 0, tzinfo=UTC)
    with database.SessionLocal() as database_session:
        job = Job(
            status=JobStatus.READY_FOR_REVIEW,
            client_name="Legacy Client",
            summary_notes="Legacy job to claim.",
            description_text="Legacy job to claim.",
            raw_start_utc=created_at_utc,
            raw_end_utc=created_at_utc,
            rounded_start_utc=created_at_utc,
            rounded_end_utc=created_at_utc,
            work_location=WorkLocation.REMOTE,
            transcription_status=TranscriptionStatus.NOT_REQUESTED,
            idempotency_key="legacy-job-to-claim",
        )
        database_session.add(job)
        database_session.commit()
        return job.id


def test_super_admin_adds_first_web_user_and_claims_existing_jobs(super_admin_client: TestClient) -> None:
    """The first managed web user should take ownership of existing unowned jobs."""

    first_user_password = "New-test-password1!"
    with database.SessionLocal() as database_session:
        database_session.execute(delete(WebUser))
        database_session.commit()
    legacy_job_id = _seed_unowned_job()

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    create_response = super_admin_client.post(
        "/users",
        data={
            "csrf_token": csrf_token,
            "full_name": "First Technician",
            "username": "first-tech",
            "password": first_user_password,
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "8",
            "autotask_resource_email": "first.tech@example.test",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "first-tech"))
        assert user is not None
        assert user.password_hash != first_user_password
        assert user.autotask_resource_id == 42
        assert user.autotask_default_service_desk_role_id == 8
        assert user.email == "first.tech@example.test"
        job = database_session.get(Job, legacy_job_id)
        assert job is not None
        assert job.web_user_id == user.id

    login_as(super_admin_client, username="first-tech", password=first_user_password)
    mobile_response = super_admin_client.get("/home")
    assert mobile_response.status_code == 200
    assert "Start a work entry" in mobile_response.text


def test_users_page_renders_table_and_edit_panels(super_admin_client: TestClient) -> None:
    """The web-user manager should render a table list with per-row edit controls."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = "tech@example.test"
        user.autotask_default_service_desk_role_id = 8
        database_session.add(
            WebAuthnCredential(
                web_user_id=user.id,
                credential_id="users-page-passkey",
                credential_public_key="users-page-public-key",
                sign_count=0,
                credential_type="public-key",
                backed_up=False,
            )
        )
        database_session.add(
            WebUser(
                full_name="No Passkey User",
                username="no-passkey",
                username_normalized="no-passkey",
                password_hash=hash_password("No-passkey-password1!"),
                autotask_resource_id=78,
            )
        )
        database_session.commit()

    users_page = super_admin_client.get("/users")

    assert users_page.status_code == 200
    assert '<table class="users-table">' in users_page.text
    assert "<th scope=\"col\">Email</th>" in users_page.text
    assert "<th scope=\"col\">Role ID</th>" in users_page.text
    assert "<th scope=\"col\">Last login</th>" in users_page.text
    assert "<th scope=\"col\">Device</th>" in users_page.text
    assert 'data-label="Email"' in users_page.text
    assert 'data-label="Default role"' in users_page.text
    assert 'data-label="Last login"' in users_page.text
    assert 'data-label="Device sign-in"' in users_page.text
    assert 'class="passkey-status-icon passkey-status-registered"' in users_page.text
    assert 'class="passkey-status-icon passkey-status-missing"' in users_page.text
    assert "Device sign-in set up" in users_page.text
    assert "No device sign-in" in users_page.text
    assert "Never" in users_page.text
    assert "tech@example.test" in users_page.text
    assert re.search(
        r'<td data-label="Default role">\s*<span class="mono-value user-default-role-value">8</span>\s*</td>',
        users_page.text,
    )
    assert 'class="mono-value user-default-role-value">Role 8<' not in users_page.text
    assert 'data-user-edit-toggle' in users_page.text
    assert 'data-user-edit-panel' in users_page.text
    assert 'title="Edit user"' in users_page.text
    assert 'title="Refresh Autotask resource"' not in users_page.text
    assert "/refresh-resource" not in users_page.text
    assert 'title="Disable user"' in users_page.text
    assert 'class="danger-outline-button user-action-icon-button"' in users_page.text
    assert 'class="secondary-link-button" href="/review"' not in users_page.text
    assert ">Edit<" not in users_page.text
    assert ">Delete<" not in users_page.text
    assert 'name="autotask_resource_email"' in users_page.text
    assert 'name="autotask_default_service_desk_role_id"' in users_page.text
    assert 'data-autotask-role-url="/users/autotask-resource-roles"' in users_page.text
    assert 'data-role-select' in users_page.text

    stylesheet = (Path(__file__).resolve().parents[1] / "job_logger" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".users-layout {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr);" in stylesheet
    assert ".users-table {\n  width: 100%;\n  min-width: 980px;" in stylesheet
    assert "white-space: nowrap;" in stylesheet
    assert ".add-user-panel {\n  position: static;" in stylesheet
    assert 'data-resource-results hidden' in users_page.text
    assert f"/static/users.js?v={static_asset_version()}" in users_page.text
    assert "The config super admin is intentionally not listed here." in users_page.text
    assert 'colspan="10"' in users_page.text


def test_successful_managed_user_login_updates_last_login(client: TestClient) -> None:
    """Successful managed-user password login should update admin-visible metadata."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        assert user.last_login_at_utc is None

    login_as_web_user(client)

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        assert user.last_login_at_utc is not None


def test_super_admin_is_read_only_for_work_entries(super_admin_client: TestClient) -> None:
    """The config super admin can view but cannot create work entries."""

    mobile_response = super_admin_client.get("/home")
    csrf_token = extract_csrf_token(mobile_response.text)
    start_response = super_admin_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert start_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(Job)) is None


def test_users_page_disables_unused_user(super_admin_client: TestClient) -> None:
    """Delete actions should disable users so future login attempts are explainable."""

    with database.SessionLocal() as database_session:
        user = WebUser(
            full_name="Delete Me",
            username="delete-me",
            username_normalized="delete-me",
            password_hash=hash_password("Delete-me-password1!"),
            autotask_resource_id=77,
        )
        database_session.add(user)
        database_session.commit()
        user_id = user.id

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    delete_response = super_admin_client.post(
        f"/users/{user_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.disabled is True
        assert user.sessions_invalidated_at_utc is not None


def test_deleted_user_session_is_cleared_and_login_shows_disabled(client: TestClient) -> None:
    """A disabled-by-delete web user should be signed out and blocked on login."""

    login_as_web_user(client)
    assert client.get("/home").status_code == 200
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id

    with TestClient(client.app) as admin_client:
        login_as_super_admin(admin_client)
        users_page = admin_client.get("/users")
        admin_csrf_token = extract_csrf_token(users_page.text)
        delete_response = admin_client.post(
            f"/users/{user_id}/delete",
            data={"csrf_token": admin_csrf_token},
            follow_redirects=False,
        )
        assert delete_response.status_code == 303
        result_page = admin_client.get("/users")
        assert "User disabled and signed out." in result_page.text
        assert 'title="Enable user"' in result_page.text

    old_session_response = client.get("/home", follow_redirects=False)
    assert old_session_response.status_code == 303
    assert old_session_response.headers["location"] == "/login"

    login_page = client.get("/login")
    assert "This user account is disabled. Contact the administrator." in login_page.text
    csrf_token = extract_csrf_token(login_page.text)
    invalid_password_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "tech", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert invalid_password_response.status_code == 303

    invalid_login_page = client.get("/login")
    assert "Invalid username or password." in invalid_login_page.text
    csrf_token = extract_csrf_token(invalid_login_page.text)
    disabled_login_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "tech", "password": TEST_WEB_USER_PASSWORD},
        follow_redirects=False,
    )
    assert disabled_login_response.status_code == 303
    assert disabled_login_response.headers["location"] == "/login"

    disabled_login_page = client.get("/login")
    assert "This user account is disabled. Contact the administrator." in disabled_login_page.text
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.disabled is True
        assert user.sessions_invalidated_at_utc is not None
        audit_events = list(database_session.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login.failed")))
        assert any(
            event.details.get("reason") == "account_disabled" and event.details.get("web_user_id") == user_id
            for event in audit_events
        )


def test_users_page_disables_user_with_job_history(
    authenticated_client: TestClient,
) -> None:
    """Users with jobs are disabled instead of deleted so history remains linked."""

    mobile_page = authenticated_client.get("/home")
    csrf_token = extract_csrf_token(mobile_page.text)
    start_response = authenticated_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert start_response.status_code == 303

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id

    login_as_super_admin(authenticated_client)
    users_page = authenticated_client.get("/users")
    admin_csrf_token = extract_csrf_token(users_page.text)
    delete_response = authenticated_client.post(
        f"/users/{user_id}/delete",
        data={"csrf_token": admin_csrf_token},
        follow_redirects=False,
    )

    assert delete_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.disabled is True
        job = database_session.scalar(select(Job).where(Job.web_user_id == user_id))
        assert job is not None

    users_page = authenticated_client.get("/users")
    assert 'title="Enable user"' in users_page.text
    admin_csrf_token = extract_csrf_token(users_page.text)
    enable_response = authenticated_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": admin_csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": "",
            "autotask_resource_id": "1",
            "autotask_resource_email": "",
            "autotask_default_service_desk_role_id": "",
        },
        follow_redirects=False,
    )

    assert enable_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.disabled is False


def test_username_suggestion_uses_first_initial_and_last_name() -> None:
    """The default username should match the requested first-initial plus last-name rule."""

    assert suggested_username_from_full_name("Joe Blow") == "jblow"
    assert suggested_username_from_full_name("  Mary Ann Van Buren  ") == "mburen"
    assert suggested_username_from_full_name("Prince") == ""


def test_managed_user_password_complexity_is_enforced(super_admin_client: TestClient) -> None:
    """Weak managed-user passwords should be rejected before the user is created."""

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    create_response = super_admin_client.post(
        "/users",
        data={
            "csrf_token": csrf_token,
            "full_name": "Weak Password",
            "username": "weak-password",
            "password": "lowercase1!",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "8",
            "autotask_resource_email": "weak@example.test",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(WebUser).where(WebUser.username == "weak-password")) is None

    follow_response = super_admin_client.get("/users")
    assert "Password must include at least one uppercase letter." in follow_response.text
    try:
        hash_password("lowercase1!")
    except WebUserError as exc:
        assert "uppercase" in str(exc)
    else:
        raise AssertionError("Weak managed-user password was accepted.")


def test_users_page_autotask_resource_lookup_is_super_admin_only(client: TestClient) -> None:
    """Only the config super admin should query Autotask resource options."""

    login_as_web_user(client)
    forbidden_response = client.get("/users/autotask-resources?query=Joe%20Blow")
    assert forbidden_response.status_code == 403

    login_as_super_admin(client)
    lookup_response = client.get("/users/autotask-resources?query=Joe%20Blow")
    assert lookup_response.status_code == 200
    payload = lookup_response.json()
    assert payload["resources"][0]["resource_id"] == 42
    assert payload["resources"][0]["resource_name"] == "Blow, Joe"
    assert payload["resources"][0]["email"] == "joe.blow@example.test"


def test_users_page_autotask_role_lookup_is_super_admin_only(client: TestClient) -> None:
    """Only the config super admin should query active service-desk role options."""

    login_as_web_user(client)
    forbidden_response = client.get("/users/autotask-resource-roles?resource_id=42")
    assert forbidden_response.status_code == 403

    login_as_super_admin(client)
    lookup_response = client.get("/users/autotask-resource-roles?resource_id=42")
    assert lookup_response.status_code == 200
    payload = lookup_response.json()
    assert payload["roles"][0] == {
        "role_id": 8,
        "name": "Service Desk",
        "label": "Service Desk (ID 8, Autotask default)",
        "is_default": True,
    }
    assert payload["roles"][1] == {
        "role_id": 15,
        "name": "Field Technician",
        "label": "Field Technician (ID 15)",
        "is_default": False,
    }


def test_users_page_persists_autotask_resource_email_on_edit(super_admin_client: TestClient) -> None:
    """The selected Autotask resource email should be stored with the managed user."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    update_response = super_admin_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": "",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "",
            "autotask_resource_email": "joe.blow@example.test",
        },
        follow_redirects=False,
    )

    assert update_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.autotask_resource_id == 42
        assert user.email == "joe.blow@example.test"

    users_page = super_admin_client.get("/users")
    assert "joe.blow@example.test" in users_page.text


def test_users_page_persists_valid_default_service_desk_role(super_admin_client: TestClient) -> None:
    """The selected default service-desk role should be stored with the managed user."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    invalid_response = super_admin_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": "",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "999",
            "autotask_resource_email": "joe.blow@example.test",
        },
        follow_redirects=False,
    )

    assert invalid_response.status_code == 303
    invalid_page = super_admin_client.get("/users")
    assert "Default service desk role must be an active role for the selected Autotask resource." in invalid_page.text
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.autotask_default_service_desk_role_id is None

    csrf_token = extract_csrf_token(invalid_page.text)
    update_response = super_admin_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": "",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "15",
            "autotask_resource_email": "joe.blow@example.test",
        },
        follow_redirects=False,
    )

    assert update_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.autotask_resource_id == 42
        assert user.autotask_default_service_desk_role_id == 15
        assert user.email == "joe.blow@example.test"
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.updated")
        )
        assert audit_event is not None
        assert audit_event.details["autotask_default_service_desk_role_id"] == 15

    users_page = super_admin_client.get("/users")
    assert "Role 15" in users_page.text
