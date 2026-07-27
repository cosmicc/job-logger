"""Tests for Cloudflare Turnstile server-side validation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any

from ticket_pilot.config import settings
from ticket_pilot.services import turnstile as turnstile_service


def _turnstile_settings(**overrides):
    """Return settings with Turnstile enabled for validation tests."""

    base_overrides = {
        "app_public_base_url": "https://ticketpilot.example.test",
        "turnstile_enabled": True,
        "turnstile_secret_key": "secret-key",
        "turnstile_verify_url": "https://turnstile.example.test/siteverify",
        "turnstile_timeout_seconds": 4.0,
    }
    base_overrides.update(overrides)
    return replace(settings, **base_overrides)


class _FakeTurnstileResponse:
    """Small httpx response double for Turnstile Siteverify tests."""

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        """Simulate a successful HTTP response."""

    def json(self) -> dict[str, Any]:
        """Return the fake Siteverify response body."""

        return self._payload


class _FakeAsyncClient:
    """Async context manager that records one Siteverify request."""

    calls: list[dict[str, Any]] = []
    response_payload: dict[str, Any] = {}

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url: str, *, data: dict[str, str]) -> _FakeTurnstileResponse:
        self.calls.append({"url": url, "data": data, "timeout": self.timeout})
        return _FakeTurnstileResponse(self.response_payload)


def _run_validation(response_token: str = "token", **settings_overrides):
    """Run the async Turnstile validator from synchronous tests."""

    return asyncio.run(
        turnstile_service.verify_turnstile_response(
            response_token=response_token,
            remote_ip="203.0.113.10",
            application_settings=_turnstile_settings(**settings_overrides),
        )
    )


def test_turnstile_validation_posts_required_siteverify_fields(monkeypatch) -> None:
    """Siteverify calls should use Cloudflare's required fields and safe retry key."""

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response_payload = {
        "success": True,
        "hostname": "ticketpilot.example.test",
        "action": "password_reset",
    }
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    result = _run_validation()

    assert result.success is True
    assert len(_FakeAsyncClient.calls) == 1
    request = _FakeAsyncClient.calls[0]
    assert request["url"] == "https://turnstile.example.test/siteverify"
    assert request["timeout"] == 4.0
    assert request["data"]["secret"] == "secret-key"
    assert request["data"]["response"] == "token"
    assert request["data"]["remoteip"] == "203.0.113.10"
    assert request["data"]["idempotency_key"]


def test_turnstile_validation_logs_safe_debug_metadata(monkeypatch, caplog) -> None:
    """Siteverify diagnostics should include useful metadata without raw tokens."""

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response_payload = {
        "success": True,
        "hostname": "ticketpilot.example.test",
        "action": "password_reset",
    }
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    with caplog.at_level(logging.DEBUG, logger="ticket_pilot.services.turnstile"):
        result = _run_validation(response_token="raw-sensitive-token")

    assert result.success is True
    assert "Turnstile Siteverify request start" in caplog.text
    assert "Turnstile Siteverify response" in caplog.text
    assert "Turnstile verification succeeded" in caplog.text
    assert "token_length=19" in caplog.text
    assert "ticketpilot.example.test" in caplog.text
    assert "raw-sensitive-token" not in caplog.text
    assert "secret-key" not in caplog.text


def test_turnstile_validation_allows_disabled_turnstile_without_dev_build(monkeypatch, caplog) -> None:
    """Disabled Turnstile should bypass Siteverify in any explicit deployment mode."""

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    with caplog.at_level(logging.INFO, logger="ticket_pilot.services.turnstile"):
        result = _run_validation(
            response_token="",
            turnstile_enabled=False,
            turnstile_secret_key="",
            dev_build=False,
            app_environment="production",
        )

    assert result.success is True
    assert result.error_codes == ()
    assert _FakeAsyncClient.calls == []
    assert "TURNSTILE_ENABLED=false" in caplog.text


def test_turnstile_validation_rejects_action_mismatch(monkeypatch) -> None:
    """Successful Siteverify responses must still match the reset action."""

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response_payload = {
        "success": True,
        "hostname": "ticketpilot.example.test",
        "action": "login",
    }
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    result = _run_validation()

    assert result.success is False
    assert result.error_codes == ("action-mismatch",)


def test_turnstile_validation_rejects_hostname_mismatch(monkeypatch) -> None:
    """Successful Siteverify responses must match the configured public hostname."""

    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response_payload = {
        "success": True,
        "hostname": "other.example.test",
        "action": "password_reset",
    }
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    result = _run_validation()

    assert result.success is False
    assert result.error_codes == ("hostname-mismatch",)


def test_turnstile_validation_rejects_oversized_token_without_siteverify(monkeypatch) -> None:
    """Cloudflare documents a 2048-character token maximum."""

    _FakeAsyncClient.calls = []
    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _FakeAsyncClient)

    result = _run_validation("x" * (turnstile_service.TURNSTILE_RESPONSE_TOKEN_MAX_LENGTH + 1))

    assert result.success is False
    assert result.error_codes == ("invalid-input-response",)
    assert _FakeAsyncClient.calls == []
