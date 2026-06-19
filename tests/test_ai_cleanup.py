"""Tests for provider-backed summary cleanup."""

from __future__ import annotations

from typing import Any

import pytest

import job_logger.services.ai_cleanup as ai_cleanup
from job_logger.config import load_settings
from job_logger.services.ai_cleanup import AiCleanupContext, AiCleanupError, cleanup_summary_text


def test_ai_cleanup_requires_enabled_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cleanup stays disabled until Docker/env explicitly enables it."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "false")

    with pytest.raises(AiCleanupError, match="disabled"):
        cleanup_summary_text(
            summary_text="fixed printer",
            cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
            actor="admin",
            application_settings=load_settings(),
        )


def test_gemini_cleanup_builds_generate_content_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini cleanup uses the generateContent request shape."""

    captured_payload: dict[str, Any] = {}

    def fake_create_gemini_response(request_payload: dict[str, Any], _application_settings: object) -> dict[str, Any]:
        captured_payload.update(request_payload)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Remote restarted the firewall and verified VPN connectivity."},
                        ],
                    },
                }
            ],
        }

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_CLEANUP_MODEL", "test-gemini-model")
    monkeypatch.setenv("AI_CLEANUP_INSTRUCTIONS", "Clean the summary.")
    monkeypatch.setattr(ai_cleanup, "_create_gemini_response", fake_create_gemini_response)

    cleanup_result = cleanup_summary_text(
        summary_text="remote restarted firewall verified vpn",
        cleanup_context=AiCleanupContext(
            job_id="job-1",
            source="review",
            job_status="ready_for_review",
            client_name="Acme Energy",
            ticket_number="T20260616.0001",
            ticket_title="VPN issue",
            work_location="remote",
        ),
        actor="admin",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "Remote restarted the firewall and verified VPN connectivity."
    assert cleanup_result.provider == "gemini"
    assert cleanup_result.model == "test-gemini-model"
    assert captured_payload["store"] is False
    assert captured_payload["systemInstruction"] == {"parts": [{"text": "Clean the summary."}]}
    assert "remote restarted firewall verified vpn" in str(captured_payload["contents"])
    assert "Acme Energy" in str(captured_payload["contents"])


def test_groq_cleanup_builds_chat_completions_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The requested grok provider value uses GroqCloud chat completions."""

    captured_payload: dict[str, Any] = {}

    def fake_create_groq_response(request_payload: dict[str, Any], _application_settings: object) -> dict[str, Any]:
        captured_payload.update(request_payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": "On-Site replaced the failed switch and verified network connectivity.",
                    },
                }
            ],
        }

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "grok")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_CLEANUP_MODEL", "test-groq-model")
    monkeypatch.setenv("AI_CLEANUP_INSTRUCTIONS", "Clean the summary.")
    monkeypatch.setattr(ai_cleanup, "_create_groq_response", fake_create_groq_response)

    cleanup_result = cleanup_summary_text(
        summary_text="onsite replaced failed switch verified network",
        cleanup_context=AiCleanupContext(job_id="job-1", source="mobile", job_status="active"),
        actor="Admin User",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "On-Site replaced the failed switch and verified network connectivity."
    assert cleanup_result.provider == "grok"
    assert cleanup_result.model == "test-groq-model"
    assert captured_payload["model"] == "test-groq-model"
    assert captured_payload["messages"][0] == {"role": "system", "content": "Clean the summary."}
    assert "onsite replaced failed switch verified network" in captured_payload["messages"][1]["content"]
    assert captured_payload["user"] != "Admin User"


def test_ai_cleanup_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the configured Gemini and Groq providers are accepted."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "openai")

    with pytest.raises(AiCleanupError, match="gemini or grok"):
        cleanup_summary_text(
            summary_text="fixed printer",
            cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
            actor="admin",
            application_settings=load_settings(),
        )


def test_ai_cleanup_rejects_oversized_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Very large notes are rejected before they are sent to a provider."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "gemini")
    monkeypatch.setenv("AI_CLEANUP_MAX_INPUT_CHARS", "10")

    with pytest.raises(AiCleanupError, match="10 characters"):
        cleanup_summary_text(
            summary_text="this summary is too long",
            cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
            actor="admin",
            application_settings=load_settings(),
        )
