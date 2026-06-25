"""Tests for speech-to-text provider configuration."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import job_logger.services.transcription as transcription_service
from job_logger.config import load_settings
from job_logger.services.transcription import (
    FasterWhisperTranscriptionProvider,
    RemoteFasterWhisperTranscriptionProvider,
    TranscriptionError,
    get_transcription_provider,
)


def test_faster_whisper_provider_is_selected_from_environment(monkeypatch) -> None:
    """The local faster-whisper provider can be selected without loading a model."""

    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper")
    monkeypatch.setenv("FASTER_WHISPER_MODEL", "base.en")
    monkeypatch.setenv("FASTER_WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("FASTER_WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("FASTER_WHISPER_DOWNLOAD_ROOT", "/models/faster-whisper")
    monkeypatch.setenv("FASTER_WHISPER_LOCAL_FILES_ONLY", "true")
    monkeypatch.setenv("FASTER_WHISPER_LANGUAGE", "en")
    monkeypatch.setenv("FASTER_WHISPER_BEAM_SIZE", "5")
    monkeypatch.setenv("FASTER_WHISPER_CPU_THREADS", "8")
    monkeypatch.setenv("FASTER_WHISPER_INITIAL_PROMPT", "Use punctuation marks.")

    provider = get_transcription_provider(load_settings())

    assert isinstance(provider, FasterWhisperTranscriptionProvider)
    assert provider.provider_name == "faster_whisper"
    assert provider.application_settings.faster_whisper_local_files_only is True
    assert provider.application_settings.faster_whisper_cpu_threads == 8
    assert provider.application_settings.faster_whisper_initial_prompt == "Use punctuation marks."


def test_faster_whisper_initial_prompt_can_be_disabled(monkeypatch) -> None:
    """Operators can blank the formatting prompt for exact provider defaults."""

    monkeypatch.setenv("FASTER_WHISPER_INITIAL_PROMPT", "")

    application_settings = load_settings()

    assert application_settings.faster_whisper_initial_prompt is None


def test_faster_whisper_initial_prompt_is_passed_to_transcribe(monkeypatch) -> None:
    """The provider must pass the configured formatting prompt to the model."""

    captured_transcribe_kwargs: dict[str, object] = {}

    class FakeWhisperModel:
        """Small model stub that records transcribe options without loading ML."""

        def transcribe(self, audio_path: str, **kwargs: object) -> tuple[list[SimpleNamespace], object]:
            captured_transcribe_kwargs.update(kwargs)
            return [SimpleNamespace(text="Finished transcript.")], object()

    monkeypatch.setattr(
        transcription_service,
        "_load_faster_whisper_model",
        lambda **_kwargs: FakeWhisperModel(),
    )
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper")
    monkeypatch.setenv("FASTER_WHISPER_INITIAL_PROMPT", "Render punctuation marks.")

    provider = FasterWhisperTranscriptionProvider(load_settings())
    result = provider.transcribe(
        audio_bytes=b"fake-webm-bytes",
        filename="recording.webm",
        content_type="audio/webm",
    )

    assert result.text == "Finished transcript."
    assert captured_transcribe_kwargs["initial_prompt"] == "Render punctuation marks."


def test_remote_faster_whisper_provider_is_selected_from_environment(monkeypatch) -> None:
    """The remote faster-whisper provider can be selected independently."""

    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster-whisper-remote")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_URL", "https://speech.example.com/transcribe")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_API_KEY", "test-token")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS", "15")

    provider = get_transcription_provider(load_settings())

    assert isinstance(provider, RemoteFasterWhisperTranscriptionProvider)
    assert provider.provider_name == "faster_whisper_remote"
    assert provider.application_settings.faster_whisper_remote_url == "https://speech.example.com/transcribe"
    assert provider.application_settings.faster_whisper_remote_api_key == "test-token"
    assert provider.application_settings.faster_whisper_remote_timeout_seconds == 15


def test_remote_faster_whisper_posts_audio_and_safe_options(monkeypatch) -> None:
    """Remote transcription sends multipart audio and server-side options only."""

    captured_request: dict[str, object] = {}

    class FakeHttpClient:
        """Small HTTP client stub that records the outbound transcription call."""

        def __init__(self, *, timeout: float) -> None:
            captured_request["timeout"] = timeout

        def __enter__(self) -> FakeHttpClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured_request["url"] = url
            captured_request.update(kwargs)
            return httpx.Response(200, json={"text": "Remote transcript."})

    monkeypatch.setattr(transcription_service.httpx, "Client", FakeHttpClient)
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper_remote")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_URL", "https://speech.example.com/transcribe")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_API_KEY", "test-token")
    monkeypatch.setenv("FASTER_WHISPER_MODEL", "small.en")
    monkeypatch.setenv("FASTER_WHISPER_LANGUAGE", "en")
    monkeypatch.setenv("FASTER_WHISPER_BEAM_SIZE", "3")
    monkeypatch.setenv("FASTER_WHISPER_INITIAL_PROMPT", "Render punctuation marks.")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS", "20")

    provider = RemoteFasterWhisperTranscriptionProvider(load_settings())
    result = provider.transcribe(
        audio_bytes=b"fake-webm-bytes",
        filename="recording.webm",
        content_type="audio/webm",
    )

    assert result.provider == "faster_whisper_remote"
    assert result.text == "Remote transcript."
    assert captured_request["url"] == "https://speech.example.com/transcribe"
    assert captured_request["timeout"] == 20
    assert captured_request["headers"] == {"Authorization": "Bearer test-token"}
    assert captured_request["data"] == {
        "model": "small.en",
        "beam_size": "3",
        "language": "en",
        "initial_prompt": "Render punctuation marks.",
    }
    audio_filename, audio_bytes, audio_content_type = captured_request["files"]["audio"]
    assert audio_filename == "recording.webm"
    assert audio_bytes == b"fake-webm-bytes"
    assert audio_content_type == "audio/webm"


def test_remote_faster_whisper_rejects_public_http(monkeypatch) -> None:
    """Public remote transcription endpoints must use HTTPS."""

    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper_remote")
    monkeypatch.setenv("FASTER_WHISPER_REMOTE_URL", "http://speech.example.com/transcribe")

    provider = RemoteFasterWhisperTranscriptionProvider(load_settings())

    with pytest.raises(TranscriptionError, match="Use HTTPS"):
        provider.transcribe(
            audio_bytes=b"fake-webm-bytes",
            filename="recording.webm",
            content_type="audio/webm",
        )
