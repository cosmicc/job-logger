"""Tests for managed web-user authentication and administration."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from job_logger import database
from job_logger.enums import JobStatus, TranscriptionStatus, WorkLocation
from job_logger.models import Job, WebUser
from job_logger.services.users import WebUserError, hash_password, suggested_username_from_full_name
from tests.conftest import extract_csrf_token, login_as, login_as_super_admin, login_as_web_user


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
        assert user.email == "first.tech@example.test"
        job = database_session.get(Job, legacy_job_id)
        assert job is not None
        assert job.web_user_id == user.id

    login_as(super_admin_client, username="first-tech", password=first_user_password)
    mobile_response = super_admin_client.get("/mobile")
    assert mobile_response.status_code == 200
    assert "Start a work entry" in mobile_response.text


def test_users_page_renders_table_and_edit_panels(super_admin_client: TestClient) -> None:
    """The web-user manager should render a table list with per-row edit controls."""

    with database.SessionLocal() as database_session:
        user = database_session.scalar(select(WebUser).where(WebUser.username == "tech"))
        assert user is not None
        user.email = "tech@example.test"
        database_session.commit()

    users_page = super_admin_client.get("/users")

    assert users_page.status_code == 200
    assert '<table class="users-table">' in users_page.text
    assert "<th scope=\"col\">Email</th>" in users_page.text
    assert 'data-label="Email"' in users_page.text
    assert "tech@example.test" in users_page.text
    assert 'data-user-edit-toggle' in users_page.text
    assert 'data-user-edit-panel' in users_page.text
    assert 'name="autotask_resource_email"' in users_page.text
    assert 'data-resource-results hidden' in users_page.text
    assert "The config super admin is intentionally not listed here." in users_page.text


def test_super_admin_is_read_only_for_work_entries(super_admin_client: TestClient) -> None:
    """The config super admin can view but cannot create work entries."""

    mobile_response = super_admin_client.get("/mobile")
    csrf_token = extract_csrf_token(mobile_response.text)
    start_response = super_admin_client.post(
        "/jobs/start",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert start_response.status_code == 303
    with database.SessionLocal() as database_session:
        assert database_session.scalar(select(Job)) is None


def test_users_page_deletes_unused_user(super_admin_client: TestClient) -> None:
    """Users with no jobs can be deleted from the manager."""

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
        assert database_session.get(WebUser, user_id) is None


def test_users_page_disables_user_with_job_history(
    authenticated_client: TestClient,
) -> None:
    """Users with jobs are disabled instead of deleted so history remains linked."""

    mobile_page = authenticated_client.get("/mobile")
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
