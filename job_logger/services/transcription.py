"""Configurable speech-to-text providers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

from job_logger.config import Settings, settings


@dataclass(frozen=True)
class TranscriptionResult:
    """Safe result returned by a transcription provider."""

    # provider is stored for review and audit.
    provider: str

    # text is the transcript shown and edited on the review page.
    text: str


class TranscriptionError(RuntimeError):
    """Raised when a provider cannot transcribe the submitted audio."""


class BaseTranscriptionProvider:
    """Interface implemented by all transcription providers."""

    provider_name = "base"

    def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
        """Convert submitted audio bytes into editable text."""

        raise NotImplementedError


class MockTranscriptionProvider(BaseTranscriptionProvider):
    """Local provider used for safe end-to-end testing without external APIs."""

    provider_name = "mock"

    def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
        """Return deterministic text that proves the audio upload path worked."""

        if not audio_bytes:
            raise TranscriptionError("No audio bytes were submitted.")

        text = f"Mock transcript from {filename}. Replace this text during review."
        return TranscriptionResult(provider=self.provider_name, text=text)


class DisabledTranscriptionProvider(BaseTranscriptionProvider):
    """Provider used when audio recording should be disabled server-side."""

    provider_name = "disabled"

    def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
        """Reject transcription attempts when the provider is disabled."""

        raise TranscriptionError("Speech-to-text is disabled by configuration.")


@lru_cache(maxsize=4)
def _load_faster_whisper_model(
    *,
    model_name: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
    download_root: str,
    local_files_only: bool,
) -> object:
    """Load and cache a faster-whisper model for repeated transcription calls."""

    from faster_whisper import WhisperModel

    # The model directory is created before loading so Docker volume mounts work
    # for both first-run downloads and local-files-only deployments.
    model_cache_path = Path(download_root)
    model_cache_path.mkdir(parents=True, exist_ok=True)
    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        download_root=str(model_cache_path),
        local_files_only=local_files_only,
    )


class FasterWhisperTranscriptionProvider(BaseTranscriptionProvider):
    """Local faster-whisper provider for real speech-to-text transcription."""

    provider_name = "faster_whisper"

    def __init__(self, application_settings: Settings) -> None:
        """Store local faster-whisper settings."""

        self.application_settings = application_settings

    def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
        """Transcribe audio locally and delete the temporary audio file."""

        if not audio_bytes:
            raise TranscriptionError("No audio bytes were submitted.")

        # faster-whisper reads through local media tooling, so a short-lived file
        # is used instead of permanently storing raw audio in the database or app.
        temporary_audio_path: Path | None = None
        try:
            submitted_suffix = Path(filename or "recording.webm").suffix or ".webm"
            with NamedTemporaryFile(prefix="job-logger-audio-", suffix=submitted_suffix, delete=False) as audio_file:
                audio_file.write(audio_bytes)
                temporary_audio_path = Path(audio_file.name)

            model = _load_faster_whisper_model(
                model_name=self.application_settings.faster_whisper_model,
                device=self.application_settings.faster_whisper_device,
                compute_type=self.application_settings.faster_whisper_compute_type,
                cpu_threads=self.application_settings.faster_whisper_cpu_threads,
                download_root=self.application_settings.faster_whisper_download_root,
                local_files_only=self.application_settings.faster_whisper_local_files_only,
            )
            segments, _transcription_info = model.transcribe(
                str(temporary_audio_path),
                language=self.application_settings.faster_whisper_language,
                beam_size=self.application_settings.faster_whisper_beam_size,
                initial_prompt=self.application_settings.faster_whisper_initial_prompt,
            )
            transcript_text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        except ImportError as exc:
            raise TranscriptionError("The faster-whisper package is not installed.") from exc
        except Exception as exc:
            raise TranscriptionError(f"Local faster-whisper transcription failed: {exc}") from exc
        finally:
            if temporary_audio_path is not None:
                temporary_audio_path.unlink(missing_ok=True)

        if not transcript_text:
            raise TranscriptionError("Local faster-whisper transcription returned no text.")

        return TranscriptionResult(provider=self.provider_name, text=transcript_text)


def get_transcription_provider(application_settings: Settings = settings) -> BaseTranscriptionProvider:
    """Return the configured speech-to-text provider."""

    if application_settings.transcription_provider == "mock":
        return MockTranscriptionProvider()

    if application_settings.transcription_provider == "faster_whisper":
        return FasterWhisperTranscriptionProvider(application_settings)

    if application_settings.transcription_provider == "disabled":
        return DisabledTranscriptionProvider()

    raise TranscriptionError(f"Unsupported transcription provider: {application_settings.transcription_provider}")
