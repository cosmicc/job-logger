"""Tests for the authenticated Help page and stateless help assistant."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from job_logger import ui as ui_context
from job_logger.config import settings
from job_logger.routes import help as help_routes
from job_logger.services.changelog import ChangelogEntry
from job_logger.services.help_assistant import HelpAssistantError, HelpAssistantResult
from job_logger.services.system_health import AppHealthIssue, AppHealthSnapshot
from tests.conftest import extract_csrf_token


def test_help_page_requires_login(client: TestClient) -> None:
    """Anonymous users should not see the authenticated help page."""

    response = client.get("/help", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_authenticated_help_page_renders_version_and_changelog(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    """Managed web users should see Help, current version text, and changelog access."""

    monkeypatch.setattr(ui_context, "collect_app_health_snapshot", lambda database_session=None: AppHealthSnapshot(issues=()))

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert 'class="help-shell"' in response.text
    assert "<h1>Help</h1>" in response.text
    assert "Ask a Job Logger question or view the version changelog." not in response.text
    assert '<h2 id="help-assistant-heading">Ask AI for help</h2>' in response.text
    assert "Ask AI for help with using Job Logger" in response.text
    assert "Single question, single answer." not in response.text
    assert 'type="text"' in response.text
    assert "data-help-question-input" in response.text
    assert "<textarea" not in response.text
    assert 'id="operational-status"' in response.text
    assert 'data-help-operational-card' in response.text
    assert "help-operational-panel-ok" in response.text
    assert ">Application status<" not in response.text
    assert ">Operational Status<" in response.text
    assert ">Operational<" in response.text
    assert "All monitored app checks are fully operational." in response.text
    assert ">v1.2.4<" in response.text
    assert '<p class="help-version-release-date">Released: 07.08.2026</p>' in response.text
    assert 'href="/changelog"' in response.text
    assert "data-help-changelog-open" in response.text
    assert "data-help-changelog-overlay" in response.text
    assert "data-help-changelog-close" in response.text
    assert "help-changelog-entry-list" in response.text
    assert "help-changelog-history-card" in response.text
    assert "changelog-marker" not in response.text
    assert "Released: 07.05.2026" in response.text
    assert "Released: 07.03.2026" in response.text
    assert "Released: 07.02.2026" in response.text
    assert ">version changelog<" in response.text
    assert "/static/help.js?v=" in response.text
    assert "AI Help is not configured. Contact your app administrator." in response.text
    assistant_index = response.text.index('class="edit-panel help-assistant-panel"')
    operational_index = response.text.index("data-help-operational-card")
    version_index = response.text.index('class="help-version-panel"')
    assert assistant_index < operational_index < version_index


def test_help_page_shows_released_current_version_date(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    """The Help current-version card should label the release date when one exists."""

    monkeypatch.setattr(ui_context, "collect_app_health_snapshot", lambda database_session=None: AppHealthSnapshot(issues=()))
    monkeypatch.setattr(
        help_routes,
        "load_changelog_entries",
        lambda: [
            ChangelogEntry(
                version="1.2.4",
                release_date="07.08.2026",
                title="Released test version",
                changes=("Released-current test note.",),
            ),
            ChangelogEntry(
                version="1.2.2",
                release_date="07.03.2026",
                title="Prior released version",
                changes=("Prior released note.",),
            ),
        ],
    )

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert '<p class="help-version-release-date">Released: 07.08.2026</p>' in response.text
    assert '<span class="release-date">Released: 07.08.2026</span>' in response.text
    assert '<span class="release-date">Released: 07.03.2026</span>' in response.text


def test_help_page_hides_health_details_from_non_admin_users(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    """Ordinary managed users should see degraded status without issue details."""

    degraded_snapshot = AppHealthSnapshot(
        issues=(
            AppHealthIssue(
                code="autotask-api",
                label="Autotask API needs attention",
                severity="critical",
                summary="Autotask company lookup could not reach the Autotask API.",
            ),
        )
    )
    monkeypatch.setattr(ui_context, "collect_app_health_snapshot", lambda database_session=None: degraded_snapshot)

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert 'data-help-operational-card' in response.text
    assert "help-operational-panel-critical" in response.text
    assert ">Degraded<" in response.text
    assert "Job Logger is degraded. An administrator can review Diagnostics for details." in response.text
    assert "data-help-operational-detail-list" not in response.text
    assert "Autotask API needs attention" not in response.text
    assert "Autotask company lookup could not reach the Autotask API." not in response.text


def test_help_page_uses_warning_operational_status_color(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    """Warning-only degraded health should use the Help warning status color."""

    warning_snapshot = AppHealthSnapshot(
        issues=(
            AppHealthIssue(
                code="disk-space",
                label="Disk space warning",
                severity="warning",
                summary="Disk free space is below the warning threshold.",
            ),
        )
    )
    monkeypatch.setattr(ui_context, "collect_app_health_snapshot", lambda database_session=None: warning_snapshot)

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert "help-operational-panel-warning" in response.text
    assert "help-operational-panel-critical" not in response.text
    assert ">Degraded<" in response.text
    assert "Job Logger is degraded. An administrator can review Diagnostics for details." in response.text
    assert "Disk space warning" not in response.text


def test_help_page_shows_health_details_to_admin_users(
    super_admin_client: TestClient,
    monkeypatch,
) -> None:
    """Diagnostics-authorized users should see specific health issue details."""

    degraded_snapshot = AppHealthSnapshot(
        issues=(
            AppHealthIssue(
                code="database-status",
                label="Database unavailable",
                severity="critical",
                summary="Database connectivity is unavailable.",
            ),
        )
    )
    monkeypatch.setattr(ui_context, "collect_app_health_snapshot", lambda database_session=None: degraded_snapshot)

    response = super_admin_client.get("/help")

    assert response.status_code == 200
    assert 'data-help-operational-card' in response.text
    assert "help-operational-panel-critical" in response.text
    assert 'data-help-operational-detail-list' in response.text
    assert "App health critical. Review Diagnostics for details and recovery actions." in response.text
    assert "Database unavailable" in response.text
    assert "Database connectivity is unavailable." in response.text


def test_help_javascript_clears_submitted_question_on_next_entry() -> None:
    """The Help form script should clear submitted text before the next question."""

    script_text = Path("job_logger/static/help.js").read_text(encoding="utf-8")

    assert "clearQuestionOnNextEntry = false" in script_text
    assert 'questionInput.addEventListener("focus", clearQuestionIfReady);' in script_text
    assert 'questionInput.addEventListener("pointerdown", clearQuestionIfReady);' in script_text
    assert 'questionInput.addEventListener("beforeinput", clearQuestionIfReady);' in script_text
    assert "clearQuestionOnNextEntry = true;" in script_text


def test_super_admin_can_view_help(super_admin_client: TestClient) -> None:
    """The config super admin should also have the authenticated Help page."""

    response = super_admin_client.get("/help")

    assert response.status_code == 200
    assert 'class="theme-dark"' in response.text
    assert "<h1>Help</h1>" in response.text


def test_help_question_requires_authentication(client: TestClient) -> None:
    """Help questions should require a signed-in session."""

    anonymous_response = client.post("/help/ask", json={"question": "How do I start work?"})
    assert anonymous_response.status_code == 401


def test_help_question_requires_csrf(authenticated_client: TestClient) -> None:
    """Help questions should require the rendered CSRF header."""

    missing_csrf_response = authenticated_client.post("/help/ask", json={"question": "How do I start work?"})
    assert missing_csrf_response.status_code == 403


def test_help_question_logs_route_request_status(
    authenticated_client: TestClient,
    monkeypatch,
    caplog,
) -> None:
    """The help endpoint should log sanitized request and completion metadata."""

    authenticated_client.app.state.application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions="Answer Job Logger support questions for end users.",
    )

    def fake_answer_help_question(*, question, application_settings, trace_id="-"):
        assert question == "How do I start work?"
        return HelpAssistantResult(
            answer_text="Tap Start Work.",
            model=application_settings.gemini_model,
            context_source_count=2,
        )

    monkeypatch.setattr(help_routes, "answer_help_question", fake_answer_help_question)
    caplog.set_level(logging.DEBUG, logger="job_logger.routes.help")
    page_response = authenticated_client.get("/help")
    csrf_token = extract_csrf_token(page_response.text)

    response = authenticated_client.post(
        "/help/ask",
        headers={"X-CSRF-Token": csrf_token},
        json={"question": "How do I start work?"},
    )

    assert response.status_code == 200
    log_text = caplog.text
    assert "AI Help request received trace_id=" in log_text
    assert "AI Help request settings trace_id=" in log_text
    assert "AI Help request completed trace_id=" in log_text
    assert "question_length=" in log_text
    assert "test-gemini-key" not in log_text
    assert "How do I start work" not in log_text
    assert "Tap Start Work" not in log_text


def test_help_question_logs_assistant_failure(
    authenticated_client: TestClient,
    monkeypatch,
    caplog,
) -> None:
    """Configured assistant failures should emit sanitized error logs."""

    authenticated_client.app.state.application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions="Answer Job Logger support questions for end users.",
    )

    def fake_answer_help_question(*, question, application_settings, trace_id="-"):
        assert question == "How do I start work?"
        raise HelpAssistantError("AI Help is disabled by configuration.")

    monkeypatch.setattr(help_routes, "answer_help_question", fake_answer_help_question)
    caplog.set_level(logging.ERROR, logger="job_logger.routes.help")
    page_response = authenticated_client.get("/help")
    csrf_token = extract_csrf_token(page_response.text)

    response = authenticated_client.post(
        "/help/ask",
        headers={"X-CSRF-Token": csrf_token},
        json={"question": "How do I start work?"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "AI Help is disabled by configuration."}
    log_text = caplog.text
    assert "AI Help request failed trace_id=" in log_text
    assert "status_code=400" in log_text
    assert "error_class=HelpAssistantError" in log_text
    assert "detail=AI Help is disabled by configuration." in log_text
    assert "test-gemini-key" not in log_text
    assert "How do I start work" not in log_text


def test_help_question_returns_single_answer(
    authenticated_client: TestClient,
    monkeypatch,
) -> None:
    """A configured assistant should return one JSON answer without database state."""

    authenticated_client.app.state.application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions="Answer Job Logger support questions for end users.",
    )

    def fake_answer_help_question(*, question, application_settings, trace_id="-"):
        assert question == "How do I start work?"
        assert application_settings.ai_help_configured is True
        assert trace_id != "-"
        return HelpAssistantResult(
            answer_text="Tap Start Work, then choose a service call or fill in the ticket details.",
            model=application_settings.gemini_model,
            context_source_count=3,
        )

    monkeypatch.setattr(help_routes, "answer_help_question", fake_answer_help_question)
    page_response = authenticated_client.get("/help")
    csrf_token = extract_csrf_token(page_response.text)

    response = authenticated_client.post(
        "/help/ask",
        headers={"X-CSRF-Token": csrf_token},
        json={"question": "How do I start work?"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Tap Start Work, then choose a service call or fill in the ticket details.",
        "model": "gemini-3.5-flash",
        "context_source_count": 3,
    }


def test_help_page_marks_dev_build(authenticated_client: TestClient) -> None:
    """The Help page should show DEV beside the current version for dev builds."""

    authenticated_client.app.state.application_settings = replace(settings, dev_build=True)

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert ">v1.2.4 DEV<" in response.text
