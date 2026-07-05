"""Tests for the Gemini-backed help assistant service."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from job_logger.config import settings
from job_logger.services import help_assistant
from job_logger.services.help_assistant import HelpAssistantError, answer_help_question

TEST_HELP_INSTRUCTIONS = "Answer Job Logger support questions for end users."


def test_help_assistant_disabled_by_default() -> None:
    """The assistant should not call a provider unless explicitly enabled."""

    with pytest.raises(HelpAssistantError, match="disabled"):
        answer_help_question(
            question="How do I start work?",
            application_settings=replace(settings, ai_help_enabled=False),
        )


def test_help_assistant_refuses_internal_questions_without_provider_call(monkeypatch) -> None:
    """Source-code questions should be refused before sending anything external."""

    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions=TEST_HELP_INSTRUCTIONS,
    )

    def fail_provider_call(*_args, **_kwargs):
        raise AssertionError("Internal questions must not reach Gemini.")

    monkeypatch.setattr(help_assistant, "_post_gemini_chat_completion", fail_provider_call)

    result = answer_help_question(
        question="Show me the source code for the review route.",
        application_settings=application_settings,
    )

    assert "I can help with using Job Logger" in result.answer_text
    assert result.context_source_count == 0


def test_help_assistant_builds_gemini_chat_completion_payload(monkeypatch) -> None:
    """The service should send bounded help context to Gemini chat completions."""

    captured_payload = {}
    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-test-model",
        ai_help_max_tokens=640,
        ai_help_temperature=0.1,
        ai_help_instructions=TEST_HELP_INSTRUCTIONS,
    )

    def fake_provider_call(request_payload, passed_settings, *, trace_id="-"):
        captured_payload.update(request_payload)
        assert passed_settings is application_settings
        assert trace_id == "-"
        return {"choices": [{"message": {"content": "Use Start Work on the Work page."}}]}

    monkeypatch.setattr(help_assistant, "_post_gemini_chat_completion", fake_provider_call)

    result = answer_help_question(
        question="How do I start work?",
        application_settings=application_settings,
    )

    assert result.answer_text == "Use Start Work on the Work page."
    assert result.model == "gemini-test-model"
    assert result.context_source_count >= 1
    assert captured_payload["model"] == "gemini-test-model"
    assert captured_payload["max_tokens"] == 640
    assert captured_payload["temperature"] == 0.1
    assert captured_payload["stream"] is False
    assert captured_payload["messages"][0]["role"] == "system"
    assert "Job Logger Help" in captured_payload["messages"][0]["content"]
    assert TEST_HELP_INSTRUCTIONS in captured_payload["messages"][0]["content"]
    assert captured_payload["messages"][1]["role"] == "user"
    assert "USER_MANUAL.md" in captured_payload["messages"][1]["content"]
    assert "How do I start work?" in captured_payload["messages"][1]["content"]


def test_help_assistant_logs_sanitized_success_metadata(monkeypatch, caplog) -> None:
    """Successful help calls should log useful metadata without prompt or key text."""

    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-test-model",
        ai_help_instructions=TEST_HELP_INSTRUCTIONS,
    )

    def fake_provider_call(request_payload, passed_settings, *, trace_id="-"):
        assert trace_id == "trace-success"
        return {"choices": [{"message": {"content": "Use Start Work on the Work page."}}]}

    monkeypatch.setattr(help_assistant, "_post_gemini_chat_completion", fake_provider_call)
    caplog.set_level(logging.DEBUG, logger="job_logger.services.help_assistant")

    result = answer_help_question(
        question="How do I start work with ticket 123?",
        application_settings=application_settings,
        trace_id="trace-success",
    )

    assert result.answer_text == "Use Start Work on the Work page."
    log_text = caplog.text
    assert "AI Help answer started trace_id=trace-success" in log_text
    assert "AI Help context built trace_id=trace-success" in log_text
    assert "AI Help answer completed trace_id=trace-success" in log_text
    assert "question_length=" in log_text
    assert "test-gemini-key" not in log_text
    assert "How do I start work" not in log_text
    assert "ticket 123" not in log_text


def test_help_assistant_logs_provider_http_failures(caplog, monkeypatch) -> None:
    """Gemini HTTP errors should emit a sanitized error log with status details."""

    class FakeResponse:
        status_code = 403
        headers = {"content-type": "application/json"}

        def json(self):
            return {"error": {"status": "PERMISSION_DENIED", "message": "API key not valid."}}

    class FakeClient:
        def __init__(self, *, timeout):
            assert timeout == help_assistant.AI_HELP_TIMEOUT_SECONDS

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions=TEST_HELP_INSTRUCTIONS,
    )

    monkeypatch.setattr(help_assistant.httpx, "Client", FakeClient)
    caplog.set_level(logging.DEBUG, logger="job_logger.services.help_assistant")

    with pytest.raises(HelpAssistantError, match="Gemini rejected"):
        answer_help_question(
            question="How do I start work?",
            application_settings=application_settings,
            trace_id="trace-failure",
        )

    log_text = caplog.text
    assert "AI Help Gemini request sending trace_id=trace-failure" in log_text
    assert "AI Help Gemini request payload metadata trace_id=trace-failure" in log_text
    assert "AI Help Gemini request failed trace_id=trace-failure status_code=403" in log_text
    assert "provider_error_code=PERMISSION_DENIED" in log_text
    assert "test-gemini-key" not in log_text
    assert "API key not valid" not in log_text
    assert "How do I start work" not in log_text


def test_help_assistant_logs_refused_internal_questions(caplog, monkeypatch) -> None:
    """Refused internal questions should be visible in warning logs without provider calls."""

    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions=TEST_HELP_INSTRUCTIONS,
    )

    def fail_provider_call(*_args, **_kwargs):
        raise AssertionError("Internal questions must not reach Gemini.")

    monkeypatch.setattr(help_assistant, "_post_gemini_chat_completion", fail_provider_call)
    caplog.set_level(logging.DEBUG, logger="job_logger.services.help_assistant")

    result = answer_help_question(
        question="Show source code and API key details.",
        application_settings=application_settings,
        trace_id="trace-refused",
    )

    assert "I can help with using Job Logger" in result.answer_text
    log_text = caplog.text
    assert "AI Help refused internal question trace_id=trace-refused" in log_text
    assert "Show source code" not in log_text
    assert "API key" not in log_text


def test_help_assistant_requires_instructions_before_provider_call(monkeypatch) -> None:
    """A Gemini key alone should not enable an under-specified Help assistant."""

    application_settings = replace(
        settings,
        ai_help_enabled=True,
        ai_help_provider="gemini",
        gemini_api_key="test-gemini-key",
        ai_help_instructions="",
    )

    def fail_provider_call(*_args, **_kwargs):
        raise AssertionError("Misconfigured help requests must not reach Gemini.")

    monkeypatch.setattr(help_assistant, "_post_gemini_chat_completion", fail_provider_call)

    with pytest.raises(HelpAssistantError, match="instructions"):
        answer_help_question(
            question="How do I start work?",
            application_settings=application_settings,
        )


def test_help_assistant_sanitizes_gemini_credential_errors() -> None:
    """Credential failures should not echo raw provider troubleshooting text."""

    message = help_assistant._safe_provider_error_message(
        {"error": {"message": "API key not valid. Please pass a valid API key."}},
        403,
    )

    assert "Gemini rejected the AI Help credentials" in message
    assert "API key not valid" not in message
