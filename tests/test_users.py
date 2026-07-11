"""Tests for managed web-user authentication and administration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from job_logger import database
from job_logger.enums import JobStatus, TranscriptionStatus, WorkLocation
from job_logger.models import AuditEvent, Job, PasswordResetToken, WebAuthnCredential, WebUser
from job_logger.routes import users as users_routes
from job_logger.services.mail import MailDeliveryResult
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
        assert user.is_admin is False
        assert user.password_must_change is True
        job = database_session.get(Job, legacy_job_id)
        assert job is not None
        assert job.web_user_id == user.id

    login_as(super_admin_client, username="first-tech", password=first_user_password)
    forced_config_response = super_admin_client.get("/config")
    assert forced_config_response.status_code == 200
    assert "Temporary password" in forced_config_response.text
    assert "Choose a new login password to continue." in forced_config_response.text
    assert "Submit from Work in Progress" not in forced_config_response.text

    blocked_home_response = super_admin_client.get("/home", follow_redirects=False)
    assert blocked_home_response.status_code == 303
    assert blocked_home_response.headers["location"] == "/config?password_required=1"

    replacement_password = "First-tech-final1!"
    csrf_token = extract_csrf_token(forced_config_response.text)
    password_change_response = super_admin_client.post(
        "/config/password",
        data={
            "csrf_token": csrf_token,
            "new_password": replacement_password,
            "confirm_password": replacement_password,
        },
        follow_redirects=False,
    )
    assert password_change_response.status_code == 303
    assert password_change_response.headers["location"] == "/home"
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "first-tech"))
        assert user is not None
        assert user.password_must_change is False

    mobile_response = super_admin_client.get("/home")
    assert mobile_response.status_code == 200
    assert "Start a work entry" in mobile_response.text
    assert "Set up faster sign-in" in mobile_response.text


def test_users_page_renders_table_and_edit_panels(super_admin_client: TestClient) -> None:
    """The web-user manager should render a table list with per-row edit controls."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = "tech@example.test"
        user.autotask_default_service_desk_role_id = 8
        user.is_admin = True
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
    assert "<th scope=\"col\">Resource ID</th>" not in users_page.text
    assert "<th scope=\"col\">Role ID</th>" not in users_page.text
    assert "<th scope=\"col\">Last login</th>" in users_page.text
    assert "<th scope=\"col\">Device</th>" in users_page.text
    assert "<th scope=\"col\">Admin</th>" in users_page.text
    assert 'data-label="Email"' in users_page.text
    assert 'data-label="Resource ID"' not in users_page.text
    assert 'data-label="Default role"' not in users_page.text
    assert 'data-label="Last login"' in users_page.text
    assert 'data-label="Device sign-in"' in users_page.text
    assert 'data-label="Admin"' in users_page.text
    assert "Admin (Debug access)" in users_page.text
    assert 'class="status-chip user-admin-chip user-admin-enabled">Admin</span>' in users_page.text
    assert 'class="status-chip user-admin-chip user-admin-standard">User</span>' in users_page.text
    assert 'class="passkey-status-icon passkey-status-registered"' in users_page.text
    assert 'class="passkey-status-icon passkey-status-missing"' in users_page.text
    assert "Device sign-in set up" in users_page.text
    assert "No device sign-in" in users_page.text
    assert "Never" in users_page.text
    assert "tech@example.test" in users_page.text
    assert 'data-user-edit-toggle' in users_page.text
    assert 'data-user-edit-panel' in users_page.text
    assert 'title="Edit user"' in users_page.text
    assert 'title="Send password reset email"' in users_page.text
    assert 'title="Send welcome email"' in users_page.text
    assert 'title="Refresh Autotask resource"' not in users_page.text
    assert "/refresh-resource" not in users_page.text
    assert 'title="Delete user"' in users_page.text
    assert 'class="danger-outline-button user-action-icon-button"' in users_page.text
    assert 'class="secondary-link-button" href="/review"' not in users_page.text
    assert ">Edit<" not in users_page.text
    assert ">Delete<" not in users_page.text
    assert 'name="autotask_resource_email"' in users_page.text
    assert 'name="autotask_default_service_desk_role_id"' in users_page.text
    assert 'name="is_admin"' in users_page.text
    assert 'name="send_welcome_email" type="checkbox" value="1" checked' in users_page.text
    assert 'data-autotask-role-url="/users/autotask-resource-roles"' in users_page.text
    assert 'data-role-select' in users_page.text

    stylesheet = (Path(__file__).resolve().parents[1] / "job_logger" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".users-layout {\n  display: grid;\n  grid-template-columns: minmax(0, 1fr);" in stylesheet
    assert ".users-table {\n  width: 100%;\n  min-width: 960px;" in stylesheet
    assert ".user-email-result-overlay" in stylesheet
    assert ".flash-email-success" in stylesheet
    assert "white-space: nowrap;" in stylesheet
    assert ".add-user-panel {\n  position: static;" in stylesheet
    users_script = (Path(__file__).resolve().parents[1] / "job_logger" / "static" / "users.js").read_text(
        encoding="utf-8"
    )
    assert "initializeEmailActionOverlay" in users_script
    assert "window.setTimeout(closeOverlay, 5000)" in users_script
    assert 'data-resource-results hidden' in users_page.text
    assert f"/static/users.js?v={static_asset_version()}" in users_page.text
    assert "The config super admin and hidden deleted users are intentionally not listed here." in users_page.text
    assert 'colspan="9"' in users_page.text


def test_add_user_sends_welcome_email_when_requested(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """The checked add-user option should send and audit the welcome email."""

    super_admin_client.app.state.application_settings = replace(
        super_admin_client.app.state.application_settings,
        app_public_base_url="https://logger.example.test",
        admin_contact_email="admin@example.test",
    )
    sent_messages: list[dict[str, object]] = []

    def fake_send_welcome_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True, provider="smtp")

    monkeypatch.setattr(users_routes, "send_welcome_email", fake_send_welcome_email)

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    create_response = super_admin_client.post(
        "/users",
        data={
            "csrf_token": csrf_token,
            "full_name": "Invite Technician",
            "username": "invite-tech",
            "password": "Invite-tech-password1!",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "",
            "autotask_resource_email": "invite.tech@example.test",
            "send_welcome_email": "1",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    assert len(sent_messages) == 1
    assert sent_messages[0]["recipient_email"] == "invite.tech@example.test"
    assert sent_messages[0]["full_name"] == "Invite Technician"
    assert sent_messages[0]["username"] == "invite-tech"
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "invite-tech"))
        assert user is not None
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.welcome_email_sent")
        )
        assert audit_event is not None
        assert audit_event.details["web_user_id"] == user.id
        assert audit_event.details["username"] == "invite-tech"
        assert audit_event.details["email_saved"] is True
        assert audit_event.details["provider"] == "smtp"
        assert audit_event.details["safe_error"] is None

    result_page = super_admin_client.get("/users")
    assert "Welcome email sent." in result_page.text


def test_add_user_skips_welcome_email_when_option_is_unchecked(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """Unchecked add-user submissions should create the user without sending welcome mail."""

    def fake_send_welcome_email(**kwargs) -> MailDeliveryResult:
        raise AssertionError("Welcome email should not be sent when the checkbox is unchecked.")

    monkeypatch.setattr(users_routes, "send_welcome_email", fake_send_welcome_email)

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    create_response = super_admin_client.post(
        "/users",
        data={
            "csrf_token": csrf_token,
            "full_name": "No Invite Technician",
            "username": "no-invite-tech",
            "password": "No-invite-password1!",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "",
            "autotask_resource_email": "no.invite@example.test",
        },
        follow_redirects=False,
    )

    assert create_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "no-invite-tech"))
        assert user is not None
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.welcome_email_sent")
        )
        assert audit_event is None


def test_super_admin_sends_user_password_reset_email(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """The Users row action should send a reset link without enabling public self-service reset."""

    super_admin_client.app.state.application_settings = replace(
        super_admin_client.app.state.application_settings,
        app_public_base_url="https://logger.example.test",
        mail_enabled=True,
        mail_from_email="joblogger@example.test",
        mail_mode="smtp",
        mail_smtp_host="smtp.example.test",
    )
    sent_messages: list[dict[str, object]] = []

    def fake_send_password_reset_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True, provider="smtp")

    monkeypatch.setattr(users_routes, "send_password_reset_email", fake_send_password_reset_email)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = "tech@example.test"
        user_id = user.id
        database_session.commit()

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    response = super_admin_client.post(
        f"/users/{user_id}/password-reset-email",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(sent_messages) == 1
    assert sent_messages[0]["recipient_email"] == "tech@example.test"
    assert str(sent_messages[0]["reset_url"]).startswith("https://logger.example.test/reset-password/")
    with database.SessionLocal() as database_session:
        reset_token = database_session.scalar(select(PasswordResetToken).where(PasswordResetToken.web_user_id == user_id))
        assert reset_token is not None
        assert reset_token.sent_to_email == "tech@example.test"
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.password_reset_email_sent")
        )
        assert audit_event is not None
        assert audit_event.details["web_user_id"] == user_id
        assert audit_event.details["reset_row_id"] == reset_token.id

    result_page = super_admin_client.get("/users")
    assert "Password reset email sent." in result_page.text
    assert 'class="flash flash-email-success">Password reset email sent.</div>' in result_page.text


def test_super_admin_resends_welcome_email_from_user_row(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """The Users row action should resend the stored welcome email to enabled users."""

    super_admin_client.app.state.application_settings = replace(
        super_admin_client.app.state.application_settings,
        app_public_base_url="https://logger.example.test",
        admin_contact_email="admin@example.test",
    )
    sent_messages: list[dict[str, object]] = []

    def fake_send_welcome_email(**kwargs) -> MailDeliveryResult:
        sent_messages.append(kwargs)
        return MailDeliveryResult(succeeded=True, provider="smtp")

    monkeypatch.setattr(users_routes, "send_welcome_email", fake_send_welcome_email)
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = "tech@example.test"
        user_id = user.id
        database_session.commit()

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    response = super_admin_client.post(
        f"/users/{user_id}/welcome-email",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(sent_messages) == 1
    assert sent_messages[0]["recipient_email"] == "tech@example.test"
    assert sent_messages[0]["username"] == "tech"
    with database.SessionLocal() as database_session:
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.welcome_email_sent")
        )
        assert audit_event is not None
        assert audit_event.details["web_user_id"] == user_id

    result_page = super_admin_client.get("/users")
    assert "Welcome email sent." in result_page.text
    assert 'class="flash flash-email-success">Welcome email sent.</div>' in result_page.text


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


def test_users_page_hard_deletes_unused_user(super_admin_client: TestClient) -> None:
    """Delete actions should fully remove users that have no jobs."""

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
        assert user is None

    result_page = super_admin_client.get("/users")
    assert "User deleted." in result_page.text
    assert "delete-me" not in result_page.text


def test_hard_deleted_user_session_is_cleared_and_login_is_generic(client: TestClient) -> None:
    """A hard-deleted web user should look like an unknown account after removal."""

    client.app.state.application_settings = replace(
        client.app.state.application_settings,
        admin_contact_email="admin@example.test",
    )
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
        assert "User deleted." in result_page.text
        assert 'title="Enable user"' not in result_page.text

    old_session_response = client.get("/home", follow_redirects=False)
    assert old_session_response.status_code == 303
    assert old_session_response.headers["location"] == "/login"

    login_page = client.get("/login")
    assert "Session expired. Sign in again." in login_page.text
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
    deleted_login_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "tech", "password": TEST_WEB_USER_PASSWORD},
        follow_redirects=False,
    )
    assert deleted_login_response.status_code == 303
    assert deleted_login_response.headers["location"] == "/login"

    deleted_login_page = client.get("/login")
    assert "Invalid username or password." in deleted_login_page.text
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is None
        audit_events = list(database_session.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login.failed")))
        assert not any(event.details.get("reason") == "account_disabled" for event in audit_events)


def test_users_page_archives_and_restores_user_with_job_history(
    authenticated_client: TestClient,
) -> None:
    """Users with jobs should be hidden and later restored by Autotask resource ID."""

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
        assert user.archived_at_utc is not None
        assert user.username.startswith("archived-")
        assert user.username_normalized.startswith("archived-")
        job = database_session.scalar(select(Job).where(Job.web_user_id == user_id))
        assert job is not None

    users_page = authenticated_client.get("/users")
    assert "User deleted and hidden. 1 linked jobs were preserved for this Autotask resource ID." in users_page.text
    assert "Test Technician" not in users_page.text
    assert 'title="Enable user"' not in users_page.text
    admin_csrf_token = extract_csrf_token(users_page.text)
    restore_response = authenticated_client.post(
        "/users",
        data={
            "csrf_token": admin_csrf_token,
            "full_name": "Restored Technician",
            "username": "tech",
            "password": "Restored-password1!",
            "autotask_resource_id": "1",
            "autotask_resource_email": "",
            "autotask_default_service_desk_role_id": "",
        },
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.full_name == "Restored Technician"
        assert user.username == "tech"
        assert user.disabled is False
        assert user.archived_at_utc is None
        assert user.password_must_change is True
        job = database_session.scalar(select(Job).where(Job.web_user_id == user_id))
        assert job is not None
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.restored")
        )
        assert audit_event is not None
        assert audit_event.details["web_user_id"] == user_id
        assert audit_event.details["restored_archived_user"] is True

    users_page = authenticated_client.get("/users")
    assert "User restored from hidden history for this Autotask resource ID." in users_page.text
    assert "Restored Technician" in users_page.text
    assert "Test Technician" not in users_page.text


def test_users_page_persists_debug_admin_flag(super_admin_client: TestClient) -> None:
    """The existing add/edit panel should persist Diagnostics admin access."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id
        assert user.is_admin is False

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
            "autotask_resource_email": "tech@example.test",
            "is_admin": "1",
        },
        follow_redirects=False,
    )

    assert update_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.is_admin is True
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.updated")
        )
        assert audit_event is not None
        assert audit_event.details["is_admin"] is True

    users_page = super_admin_client.get("/users")
    assert 'class="status-chip user-admin-chip user-admin-enabled">Admin</span>' in users_page.text

    csrf_token = extract_csrf_token(users_page.text)
    remove_response = super_admin_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": "",
            "autotask_resource_id": "42",
            "autotask_default_service_desk_role_id": "",
            "autotask_resource_email": "tech@example.test",
        },
        follow_redirects=False,
    )

    assert remove_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.is_admin is False


def test_super_admin_password_reset_requires_managed_user_password_change(super_admin_client: TestClient) -> None:
    """A super-admin reset password should become temporary and sign out old sessions."""

    reset_password = "Reset-password1!"
    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user_id = user.id
        assert user.password_must_change is False

    users_page = super_admin_client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    reset_response = super_admin_client.post(
        f"/users/{user_id}/update",
        data={
            "csrf_token": csrf_token,
            "full_name": "Test Technician",
            "username": "tech",
            "password": reset_password,
            "autotask_resource_id": "1",
            "autotask_default_service_desk_role_id": "",
            "autotask_resource_email": "",
        },
        follow_redirects=False,
    )

    assert reset_response.status_code == 303
    with database.SessionLocal() as database_session:
        user = database_session.get(WebUser, user_id)
        assert user is not None
        assert user.password_must_change is True
        assert user.sessions_invalidated_at_utc is not None
        audit_event = database_session.scalar(
            select(AuditEvent).where(AuditEvent.action == "user.web.updated")
        )
        assert audit_event is not None
        assert audit_event.details["password_changed"] == "[redacted]"

    login_as(super_admin_client, username="tech", password=reset_password)
    config_response = super_admin_client.get("/config")
    assert "Temporary password" in config_response.text
    assert "Device sign-in" not in config_response.text


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
    assert payload["resources"][0]["resource_name"] == "Joe Blow"
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
