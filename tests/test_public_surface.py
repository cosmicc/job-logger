"""Regression tests for the unauthenticated public surface."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from tests.conftest import TEST_WEB_USER_PASSWORD, extract_csrf_token
from ticket_pilot.config import settings
from ticket_pilot.main import create_app

BROWSER_ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class UnavailableDatabaseMonitor:
    """Test double that keeps the app in database-unavailable mode."""

    def __init__(self) -> None:
        """Track whether the app records an unavailable operation."""

        self.marked_unavailable = False

    def database_available(self, application_settings, *, force: bool = False) -> bool:
        """Return unavailable for every DB-backed request."""

        return False

    def mark_unavailable(self) -> None:
        """Record that an exception path marked the database unavailable."""

        self.marked_unavailable = True


def test_login_browser_title_starts_with_ticketpilot(client: TestClient) -> None:
    """Public browser titles should put the application name first."""

    response = client.get("/login")

    assert response.status_code == 200
    assert "<title>TicketPilot - Login</title>" in response.text


def test_anonymous_sensitive_pages_redirect_to_login(client: TestClient) -> None:
    """Normal browser pages with app data should not render without a session."""

    for path in ("/work", "/review", "/users", "/diagnostics", "/config", "/changelog", "/help"):
        response = client.get(path, follow_redirects=False)

        assert response.status_code == 303, path
        assert response.headers["location"] == "/login", path


def test_anonymous_json_and_action_routes_require_authentication(client: TestClient) -> None:
    """Workflow and admin helper endpoints should reject anonymous requests."""

    get_paths = (
        "/work/service-calls",
        "/autotask/companies?query=Acme",
        "/users/autotask-resources?query=Joe",
        "/users/autotask-resource-roles?resource_id=123",
        "/review/job-1/tickets",
        "/review/job-1/ticket-notes",
        "/review/job-1/ticket-time-entries",
        "/diagnostics/logs/login-failures",
        "/diagnostics/logs/login-successes",
    )
    for path in get_paths:
        response = client.get(path, follow_redirects=False)

        assert response.status_code in {400, 401, 403, 303}, path
        assert response.status_code != 200, path

    post_paths = (
        "/jobs/start",
        "/jobs/start/service-call",
        "/jobs/job-1/ticket-number",
        "/jobs/job-1/ticket",
        "/jobs/job-1/delete",
        "/jobs/job-1/end",
        "/jobs/job-1/description/text",
        "/jobs/job-1/summary/cleanup",
        "/help/ask",
        "/review/job-1/save",
        "/review/job-1/client",
        "/review/job-1/accept",
        "/review/job-1/retry",
        "/review/job-1/ticket",
        "/review/job-1/purge",
        "/diagnostics/autotask/test",
        "/diagnostics/sessions/logout-web-users",
    )
    for path in post_paths:
        response = client.post(path, data={}, follow_redirects=False)

        assert response.status_code in {400, 401, 403, 303, 422}, path
        assert response.status_code != 200, path


def test_public_app_shell_metadata_contains_no_private_workflow_data(client: TestClient) -> None:
    """The intentional public PWA metadata should stay limited to app-shell assets."""

    manifest_response = client.get("/manifest.webmanifest")
    service_worker_response = client.get("/service-worker.js")
    icon_response = client.get("/static/icons/ticketpilot-app-icon-128.png")

    assert manifest_response.status_code == 200
    assert service_worker_response.status_code == 200
    assert icon_response.status_code == 200
    public_text = manifest_response.text + service_worker_response.text
    assert "csrf" not in public_text.lower()
    assert "ticket_pilot_session" not in public_text
    assert "APP_PASSWORD" not in public_text
    assert "ticket_number" not in public_text
    assert "summary_notes" not in public_text
    assert "caches.open" not in service_worker_response.text


def test_browser_missing_page_renders_app_error_for_anonymous_users(client: TestClient) -> None:
    """Browser navigation to a missing app route should show a TicketPilot error page."""

    response = client.get(
        "/does-not-exist",
        headers={"Accept": BROWSER_ACCEPT_HEADER},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Page not found" in response.text
    assert "Back to Login" in response.text
    assert 'href="/login"' in response.text
    assert '{"detail":"Not Found"}' not in response.text


def test_browser_missing_page_renders_work_button_for_authenticated_users(authenticated_client: TestClient) -> None:
    """Authenticated browser error pages should route the user back to Work."""

    response = authenticated_client.get(
        "/does-not-exist",
        headers={"Accept": BROWSER_ACCEPT_HEADER},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert "Page not found" in response.text
    assert "Back to Work" in response.text
    assert 'href="/work"' in response.text
    assert "Back to Login" not in response.text


def test_json_missing_page_keeps_default_not_found_shape(client: TestClient) -> None:
    """API-style clients should not receive the browser error page."""

    response = client.get(
        "/does-not-exist",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_login_after_error_page_uses_fresh_login_flow(client: TestClient) -> None:
    """Returning to Login from an error page should not poison the next sign-in."""

    error_response = client.get(
        "/does-not-exist",
        headers={"Accept": BROWSER_ACCEPT_HEADER},
        follow_redirects=False,
    )
    assert error_response.status_code == 404

    login_page_response = client.get("/login", follow_redirects=False)
    csrf_token = extract_csrf_token(login_page_response.text)
    login_response = client.post(
        "/login",
        data={"csrf_token": csrf_token, "username": "tech", "password": TEST_WEB_USER_PASSWORD},
        follow_redirects=False,
    )

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/work"


def test_generated_api_docs_and_public_health_are_closed_at_app_or_proxy(client: TestClient) -> None:
    """Schema/docs are disabled in FastAPI, and nginx blocks private health publicly."""

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404

    # The app health endpoint is intentionally unauthenticated for private
    # Docker health checks; the internet-facing nginx template blocks it.
    assert client.get("/health/live").status_code == 200


def test_database_unavailable_mode_serves_styled_retry_page() -> None:
    """DB-backed pages should show a safe app-styled page while PostgreSQL is down."""

    monitor = UnavailableDatabaseMonitor()
    test_app = create_app(
        replace(settings, automatic_backups_enabled=False),
        database_availability_monitor=monitor,
    )
    with TestClient(test_app) as test_client:
        login_response = test_client.get(
            "/login",
            headers={"Accept": BROWSER_ACCEPT_HEADER},
            follow_redirects=False,
        )
        json_response = test_client.get(
            "/work/service-calls",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        health_response = test_client.get("/health/live", follow_redirects=False)
        stylesheet_response = test_client.get("/static/service-unavailable.css", follow_redirects=False)

    assert login_response.status_code == 503
    assert "text/html" in login_response.headers["content-type"]
    assert login_response.headers["cache-control"] == "no-store"
    assert login_response.headers["retry-after"] == "10"
    assert "Service Temporarily Unavailable" in login_response.text
    assert '<meta http-equiv="refresh" content="10;url=/login">' in login_response.text
    assert "/static/app.css" in login_response.text
    assert "/static/service-unavailable.css" in login_response.text
    assert "service-unavailable-brand" not in login_response.text
    assert "<title>TicketPilot - Service Temporarily Unavailable</title>" in login_response.text
    assert "maskable" not in login_response.text
    assert "Work logging service" not in login_response.text
    assert "Temporary outage" in login_response.text
    assert "database" not in login_response.text.lower()
    assert "postgres" not in login_response.text.lower()
    assert "traceback" not in login_response.text.lower()
    assert "DATABASE_URL" not in login_response.text
    assert json_response.status_code == 503
    assert json_response.json() == {"detail": "Service temporarily unavailable."}
    assert health_response.status_code == 200
    assert stylesheet_response.status_code == 200
