"""Regression tests for the unauthenticated public surface."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_anonymous_sensitive_pages_redirect_to_login(client: TestClient) -> None:
    """Normal browser pages with app data should not render without a session."""

    for path in ("/home", "/review", "/users", "/debug", "/config", "/changelog"):
        response = client.get(path, follow_redirects=False)

        assert response.status_code == 303, path
        assert response.headers["location"] == "/login", path


def test_anonymous_json_and_action_routes_require_authentication(client: TestClient) -> None:
    """Workflow and admin helper endpoints should reject anonymous requests."""

    get_paths = (
        "/home/service-calls",
        "/autotask/companies?query=Acme",
        "/users/autotask-resources?query=Joe",
        "/users/autotask-resource-roles?resource_id=123",
        "/review/job-1/tickets",
        "/review/job-1/ticket-notes",
        "/review/job-1/ticket-time-entries",
        "/debug/logs/login-failures",
        "/debug/logs/login-successes",
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
        "/review/job-1/save",
        "/review/job-1/client",
        "/review/job-1/accept",
        "/review/job-1/retry",
        "/review/job-1/ticket",
        "/review/job-1/purge",
        "/debug/autotask/test",
        "/debug/sessions/logout-web-users",
    )
    for path in post_paths:
        response = client.post(path, data={}, follow_redirects=False)

        assert response.status_code in {400, 401, 403, 303, 422}, path
        assert response.status_code != 200, path


def test_public_app_shell_metadata_contains_no_private_workflow_data(client: TestClient) -> None:
    """The intentional public PWA metadata should stay limited to app-shell assets."""

    manifest_response = client.get("/manifest.webmanifest")
    service_worker_response = client.get("/service-worker.js")
    icon_response = client.get("/static/icons/job-logger-icon-192.png")

    assert manifest_response.status_code == 200
    assert service_worker_response.status_code == 200
    assert icon_response.status_code == 200
    public_text = manifest_response.text + service_worker_response.text
    assert "csrf" not in public_text.lower()
    assert "job_logger_session" not in public_text
    assert "APP_PASSWORD" not in public_text
    assert "ticket_number" not in public_text
    assert "summary_notes" not in public_text
    assert "caches.open" not in service_worker_response.text


def test_generated_api_docs_and_public_health_are_closed_at_app_or_proxy(client: TestClient) -> None:
    """Schema/docs are disabled in FastAPI, and nginx blocks private health publicly."""

    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404

    # The app health endpoint is intentionally unauthenticated for private
    # Docker health checks; the internet-facing nginx template blocks it.
    assert client.get("/health/live").status_code == 200
