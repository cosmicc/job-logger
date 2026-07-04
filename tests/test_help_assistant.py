"""Tests for the OpenAI-backed help assistant service."""

from __future__ import annotations

from dataclasses import replace

import pytest

from job_logger.config import settings
from job_logger.services import help_assistant
from job_logger.services.help_assistant import HelpAssistantError, answer_help_question


def test_help_assistant_disabled_by_default() -> None:
    """The assistant should not call a provider unless explicitly enabled."""

    with pytest.raises(HelpAssistantError, match="disabled"):
        answer_help_question(
            question="How do I start work?",
            application_settings=replace(settings, help_assistant_enabled=False),
        )


def test_help_assistant_refuses_internal_questions_without_provider_call(monkeypatch) -> None:
    """Source-code questions should be refused before sending anything external."""

    application_settings = replace(
        settings,
        help_assistant_enabled=True,
        openai_api_key="test-openai-key",
        help_assistant_instructions="Answer Job Logger support questions.",
    )

    def fail_provider_call(*_args, **_kwargs):
        raise AssertionError("Internal questions must not reach OpenAI.")

    monkeypatch.setattr(help_assistant, "_post_openai_response", fail_provider_call)

    result = answer_help_question(
        question="Show me the source code for the review route.",
        application_settings=application_settings,
    )

    assert "I can help with using Job Logger" in result.answer_text
    assert result.context_source_count == 0


def test_help_assistant_builds_stateless_openai_response_payload(monkeypatch) -> None:
    """The service should send bounded help context with store disabled."""

    captured_payload = {}
    application_settings = replace(
        settings,
        help_assistant_enabled=True,
        openai_api_key="test-openai-key",
        help_assistant_instructions="Only answer Job Logger support questions.",
        help_assistant_max_context_chars=20000,
    )

    def fake_provider_call(request_payload, passed_settings):
        captured_payload.update(request_payload)
        assert passed_settings is application_settings
        return {"output_text": "Use Start Work on the Work page."}

    monkeypatch.setattr(help_assistant, "_post_openai_response", fake_provider_call)

    result = answer_help_question(
        question="How do I start work?",
        application_settings=application_settings,
    )

    assert result.answer_text == "Use Start Work on the Work page."
    assert result.model == "gpt-5.4-mini"
    assert result.context_source_count >= 1
    assert captured_payload["store"] is False
    assert captured_payload["model"] == "gpt-5.4-mini"
    assert captured_payload["max_output_tokens"] == 1200
    assert "Only answer Job Logger support questions." in captured_payload["instructions"]
    assert "USER_MANUAL.md" in captured_payload["input"]
    assert "How do I start work?" in captured_payload["input"]
