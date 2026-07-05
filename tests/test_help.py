"""Tests for the authenticated Help page and stateless help assistant."""

from __future__ import annotations

import logging
from dataclasses import replace

from fastapi.testclient import TestClient

from job_logger.config import settings
from job_logger.routes import help as help_routes
from job_logger.services.help_assistant import HelpAssistantError, HelpAssistantResult
from tests.conftest import extract_csrf_token


def test_help_page_requires_login(client: TestClient) -> None:
    """Anonymous users should not see the authenticated help page."""

    response = client.get("/help", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_authenticated_help_page_renders_version_and_changelog(authenticated_client: TestClient) -> None:
    """Managed web users should see Help, current version text, and changelog access."""

    response = authenticated_client.get("/help")

    assert response.status_code == 200
    assert 'class="help-shell"' in response.text
    assert "<h1>Help</h1>" in response.text
    assert '<h2 id="help-assistant-heading">Ask AI Help</h2>' in response.text
    assert "Single question, single answer." not in response.text
    assert 'type="text"' in response.text
    assert "data-help-question-input" in response.text
    assert "<textarea" not in response.text
    assert ">v1.2.3<" in response.text
    assert 'href="/changelog"' in response.text
    assert "data-help-changelog-open" in response.text
    assert "data-help-changelog-overlay" in response.text
    assert "data-help-changelog-close" in response.text
    assert ">version changelog<" in response.text
    assert "/static/help.js?v=" in response.text
    assert "AI Help is not configured. Contact your app administrator." in response.text


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
    assert ">v1.2.3 DEV<" in response.text
