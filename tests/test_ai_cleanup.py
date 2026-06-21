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


def test_ollama_cleanup_builds_generate_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama cleanup should use a local non-streaming generate request."""

    captured_payload: dict[str, Any] = {}

    def fake_create_ollama_response(request_payload: dict[str, Any], _application_settings: object) -> dict[str, Any]:
        captured_payload.update(request_payload)
        return {"response": "Remote restarted the firewall and confirmed backups."}

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CLEANUP_MODEL", "test-ollama-model")
    monkeypatch.setenv("AI_CLEANUP_INSTRUCTIONS", "Clean the summary.")
    monkeypatch.setattr(ai_cleanup, "_create_ollama_response", fake_create_ollama_response)

    cleanup_result = cleanup_summary_text(
        summary_text="remote restarted firewall backups good",
        cleanup_context=AiCleanupContext(job_id="job-1", source="mobile", job_status="active"),
        actor="admin",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "Remote restarted the firewall and confirmed backups."
    assert cleanup_result.provider == "ollama"
    assert cleanup_result.model == "test-ollama-model"
    assert captured_payload["model"] == "test-ollama-model"
    assert captured_payload["system"] == "Clean the summary."
    assert "remote restarted firewall backups good" in captured_payload["prompt"]
    assert captured_payload["stream"] is False
    assert captured_payload["options"]["temperature"] == 0.2


def test_lm_studio_cleanup_builds_openai_compatible_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """LM Studio cleanup should use local OpenAI-compatible chat completions."""

    captured_payload: dict[str, Any] = {}

    def fake_create_lm_studio_response(request_payload: dict[str, Any], _application_settings: object) -> dict[str, Any]:
        captured_payload.update(request_payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": "On-Site replaced the access point and verified coverage.",
                    },
                }
            ],
        }

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "lm-studio")
    monkeypatch.setenv("LM_STUDIO_CLEANUP_MODEL", "test-lm-studio-model")
    monkeypatch.setenv("AI_CLEANUP_INSTRUCTIONS", "Clean the summary.")
    monkeypatch.setattr(ai_cleanup, "_create_lm_studio_response", fake_create_lm_studio_response)

    cleanup_result = cleanup_summary_text(
        summary_text="onsite replaced ap checked signal",
        cleanup_context=AiCleanupContext(job_id="job-1", source="review", job_status="ready_for_review"),
        actor="admin",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "On-Site replaced the access point and verified coverage."
    assert cleanup_result.provider == "lm_studio"
    assert cleanup_result.model == "test-lm-studio-model"
    assert captured_payload["model"] == "test-lm-studio-model"
    assert captured_payload["messages"][0] == {"role": "system", "content": "Clean the summary."}
    assert "onsite replaced ap checked signal" in captured_payload["messages"][1]["content"]
    assert captured_payload["stream"] is False


def test_ollama_cleanup_allows_private_network_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama cleanup may target a private LAN server reachable by the app."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CLEANUP_API_BASE_URL", "http://172.25.1.99:11234/api")
    captured_request: dict[str, Any] = {}

    def fake_post_provider_json(**kwargs: Any) -> dict[str, Any]:
        captured_request.update(kwargs)
        return {"response": "Remote restarted the backup service and verified alerts."}

    monkeypatch.setattr(ai_cleanup, "_post_provider_json", fake_post_provider_json)

    cleanup_result = cleanup_summary_text(
        summary_text="remote restarted backups checked alerts",
        cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
        actor="admin",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "Remote restarted the backup service and verified alerts."
    assert captured_request["provider_label"] == "Ollama"
    assert captured_request["url"] == "http://172.25.1.99:11234/api/generate"


def test_lm_studio_cleanup_allows_private_network_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """LM Studio cleanup may target a private LAN OpenAI-compatible server."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "lm_studio")
    monkeypatch.setenv("LM_STUDIO_CLEANUP_API_BASE_URL", "http://172.25.1.99:11234/v1")
    monkeypatch.setenv("LM_STUDIO_API_KEY", "local-lm-studio-key")
    captured_request: dict[str, Any] = {}

    def fake_post_provider_json(**kwargs: Any) -> dict[str, Any]:
        captured_request.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "On-Site replaced the firewall and verified failover.",
                    },
                }
            ],
        }

    monkeypatch.setattr(ai_cleanup, "_post_provider_json", fake_post_provider_json)

    cleanup_result = cleanup_summary_text(
        summary_text="onsite replaced firewall checked failover",
        cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
        actor="admin",
        application_settings=load_settings(),
    )

    assert cleanup_result.cleaned_text == "On-Site replaced the firewall and verified failover."
    assert captured_request["provider_label"] == "LM Studio"
    assert captured_request["url"] == "http://172.25.1.99:11234/v1/chat/completions"
    assert captured_request["headers"]["Authorization"] == "Bearer local-lm-studio-key"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com/api",
        "http://8.8.8.8:11434/api",
    ],
)
def test_local_ai_cleanup_rejects_public_provider_url(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    """Local-model providers must not accept arbitrary public cleanup endpoints."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_CLEANUP_API_BASE_URL", base_url)

    with pytest.raises(AiCleanupError, match="private-network URL"):
        cleanup_summary_text(
            summary_text="fixed printer",
            cleanup_context=AiCleanupContext(job_id="job-1", source="test", job_status="active"),
            actor="admin",
            application_settings=load_settings(),
        )


def test_ai_cleanup_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the configured cleanup providers are accepted."""

    monkeypatch.setenv("AI_CLEANUP_ENABLED", "true")
    monkeypatch.setenv("AI_CLEANUP_PROVIDER", "openai")

    with pytest.raises(AiCleanupError, match="gemini, grok, ollama, or lm_studio"):
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
