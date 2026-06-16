"""Tests for speech-to-text provider configuration."""

from __future__ import annotations

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

    provider = get_transcription_provider(load_settings())

    assert isinstance(provider, FasterWhisperTranscriptionProvider)
    assert provider.provider_name == "faster_whisper"
    assert provider.application_settings.faster_whisper_local_files_only is True
