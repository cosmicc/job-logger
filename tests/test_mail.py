"""Tests for password-reset mail delivery providers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from job_logger.config import settings
from job_logger.services import mail as mail_service


def _mail_settings(**overrides):
    """Return settings configured for SMTP2GO mail tests."""

    base_overrides = {
        "mail_enabled": True,
        "mail_from_email": "joblogger@example.test",
        "mail_from_name": "Job Logger",
        "mail_mode": "smtp2go",
        "mail_smtp_host": "",
        "mail_smtp2go_api_key": "api-test-key",
        "mail_smtp_timeout_seconds": 6.0,
        "password_reset_token_ttl_hours": 24.0,
    }
    base_overrides.update(overrides)
    return replace(settings, **base_overrides)


class _FakeSmtp2goResponse:
    """Small httpx response double for SMTP2GO API tests."""

    def __init__(self, payload: dict[str, Any], *, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.request = httpx.Request("POST", mail_service.SMTP2GO_EMAIL_SEND_URL)

    def raise_for_status(self) -> None:
        """Raise an HTTPStatusError for non-2xx responses."""

        if self.status_code >= 400:
            raise httpx.HTTPStatusError("SMTP2GO API failed.", request=self.request, response=self)

    def json(self) -> dict[str, Any]:
        """Return the fake SMTP2GO response body."""

        return self._payload


class _FakeHttpClient:
    """Context manager that records one SMTP2GO request."""

    calls: list[dict[str, Any]] = []
    response = _FakeSmtp2goResponse(
        {"data": {"succeeded": 1, "failed": 0, "failures": [], "email_id": "email-id"}}
    )

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self) -> _FakeHttpClient:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _FakeSmtp2goResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
        return self.response


def test_smtp2go_password_reset_email_posts_standard_email_payload(monkeypatch) -> None:
    """SMTP2GO mode should use the documented Standard Email JSON endpoint."""

    _FakeHttpClient.calls = []
    _FakeHttpClient.response = _FakeSmtp2goResponse(
        {"data": {"succeeded": 1, "failed": 0, "failures": [], "email_id": "email-id"}}
    )
    monkeypatch.setattr(mail_service.httpx, "Client", _FakeHttpClient)

    result = mail_service.send_password_reset_email(
        recipient_email="tech@example.test",
        reset_url="https://logger.example.test/reset-password/token",
        application_settings=_mail_settings(),
    )

    assert result.succeeded is True
    assert result.provider == "smtp2go"
    assert len(_FakeHttpClient.calls) == 1
    request = _FakeHttpClient.calls[0]
    assert request["url"] == "https://api.smtp2go.com/v3/email/send"
    assert request["timeout"] == 6.0
    assert request["headers"]["X-Smtp2go-Api-Key"] == "api-test-key"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["json"]["sender"] == "Job Logger <joblogger@example.test>"
    assert request["json"]["to"] == ["tech@example.test"]
    assert request["json"]["subject"] == "Reset your Job Logger password"
    assert "https://logger.example.test/reset-password/token" in request["json"]["text_body"]


def test_smtp2go_password_reset_email_reports_api_failure(monkeypatch) -> None:
    """SMTP2GO API failures should return a bounded provider-specific error."""

    _FakeHttpClient.calls = []
    _FakeHttpClient.response = _FakeSmtp2goResponse(
        {
            "data": {
                "error_code": "E_ApiResponseCodes.ENDPOINT_PERMISSION_DENIED",
                "error": "You do not have permission to access this API endpoint",
            }
        },
        status_code=400,
    )
    monkeypatch.setattr(mail_service.httpx, "Client", _FakeHttpClient)

    result = mail_service.send_password_reset_email(
        recipient_email="tech@example.test",
        reset_url="https://logger.example.test/reset-password/token",
        application_settings=_mail_settings(),
    )

    assert result.succeeded is False
    assert result.provider == "smtp2go"
    assert result.safe_error is not None
    assert "SMTP2GO HTTP 400" in result.safe_error
    assert "ENDPOINT_PERMISSION_DENIED" in result.safe_error


def test_smtp2go_password_reset_email_rejects_malformed_success_payload(monkeypatch) -> None:
    """Unexpected SMTP2GO success payloads should fail closed without raising."""

    _FakeHttpClient.calls = []
    _FakeHttpClient.response = _FakeSmtp2goResponse({"data": {"succeeded": "unknown", "failed": 0}})
    monkeypatch.setattr(mail_service.httpx, "Client", _FakeHttpClient)

    result = mail_service.send_password_reset_email(
        recipient_email="tech@example.test",
        reset_url="https://logger.example.test/reset-password/token",
        application_settings=_mail_settings(),
    )

    assert result.succeeded is False
    assert result.provider == "smtp2go"
    assert result.safe_error is not None
    assert "SMTP2GO delivery was not accepted" in result.safe_error
