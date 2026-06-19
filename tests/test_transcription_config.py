"""Tests for speech-to-text provider configuration."""

from __future__ import annotations

from types import SimpleNamespace

import job_logger.services.transcription as transcription_service
from job_logger.config import load_settings
from job_logger.services.transcription import FasterWhisperTranscriptionProvider, get_transcription_provider


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
