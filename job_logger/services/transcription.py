"""Configurable speech-to-text providers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse

import httpx

from job_logger.config import Settings, settings

PRIVATE_TRANSCRIPTION_HOSTNAMES = {
    "localhost",
    "host.docker.internal",
    "gateway.docker.internal",
    "host.containers.internal",
}
PRIVATE_TRANSCRIPTION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


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


def _is_private_transcription_hostname(hostname: str | None) -> bool:
    """Return whether a hostname points at loopback or private-network space."""

    if hostname is None:
        return False

    normalized_hostname = hostname.strip().strip("[]").lower()
    if normalized_hostname in PRIVATE_TRANSCRIPTION_HOSTNAMES:
        return True

    try:
        ip_address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        return False

    if ip_address.is_unspecified or ip_address.is_multicast:
        return False

    return any(ip_address in private_network for private_network in PRIVATE_TRANSCRIPTION_NETWORKS)


def _validate_remote_faster_whisper_url(remote_url: str) -> str:
    """Return a normalized remote faster-whisper URL or reject unsafe targets."""

    normalized_url = (remote_url or "").strip().rstrip("/")
    parsed_url = urlparse(normalized_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise TranscriptionError("Remote faster-whisper requires FASTER_WHISPER_REMOTE_URL with an HTTP endpoint.")

    if parsed_url.scheme == "http" and not _is_private_transcription_hostname(parsed_url.hostname):
        raise TranscriptionError(
            "Remote faster-whisper HTTP endpoints must use loopback or private-network hosts. "
            "Use HTTPS for public remote transcription endpoints."
        )

    return normalized_url


def _safe_remote_error_message(response_payload: Any) -> str:
    """Return a bounded remote transcription error without exposing internals."""

    if isinstance(response_payload, dict):
        for key in ("detail", "message", "error"):
            error_value = response_payload.get(key)
            if isinstance(error_value, str) and error_value.strip():
                return error_value.strip()[:300]
            if isinstance(error_value, dict):
                nested_message = error_value.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message.strip()[:300]

    return "Remote faster-whisper transcription failed."


def _remote_transcript_text(response_payload: Any) -> str:
    """Extract the transcript text from the documented remote response shape."""

    if not isinstance(response_payload, dict):
        return ""

    for key in ("text", "transcript"):
        transcript_text = response_payload.get(key)
        if isinstance(transcript_text, str) and transcript_text.strip():
            return transcript_text.strip()

    return ""


class RemoteFasterWhisperTranscriptionProvider(BaseTranscriptionProvider):
    """HTTP-backed faster-whisper provider for a trusted remote transcription server."""

    provider_name = "faster_whisper_remote"

    def __init__(self, application_settings: Settings) -> None:
        """Store remote faster-whisper settings."""

        self.application_settings = application_settings

    def transcribe(self, *, audio_bytes: bytes, filename: str, content_type: str) -> TranscriptionResult:
        """Send audio to a configured remote faster-whisper API and return text."""

        if not audio_bytes:
            raise TranscriptionError("No audio bytes were submitted.")

        remote_url = _validate_remote_faster_whisper_url(self.application_settings.faster_whisper_remote_url)
        headers: dict[str, str] = {}
        if self.application_settings.faster_whisper_remote_api_key:
            headers["Authorization"] = f"Bearer {self.application_settings.faster_whisper_remote_api_key}"

        form_data = {
            "model": self.application_settings.faster_whisper_model,
            "beam_size": str(self.application_settings.faster_whisper_beam_size),
        }
        if self.application_settings.faster_whisper_language:
            form_data["language"] = self.application_settings.faster_whisper_language
        if self.application_settings.faster_whisper_initial_prompt:
            form_data["initial_prompt"] = self.application_settings.faster_whisper_initial_prompt

        safe_filename = filename or "recording.webm"
        safe_content_type = content_type or "application/octet-stream"
        try:
            with httpx.Client(timeout=self.application_settings.faster_whisper_remote_timeout_seconds) as client:
                response = client.post(
                    remote_url,
                    headers=headers,
                    data=form_data,
                    files={"audio": (safe_filename, audio_bytes, safe_content_type)},
                )
        except httpx.TimeoutException as exc:
            raise TranscriptionError("Remote faster-whisper transcription timed out. Try again.") from exc
        except httpx.RequestError as exc:
            raise TranscriptionError("Remote faster-whisper request could not be completed.") from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}

        if response.status_code >= 400:
            raise TranscriptionError(_safe_remote_error_message(response_payload))

        transcript_text = _remote_transcript_text(response_payload)
        if not transcript_text:
            raise TranscriptionError("Remote faster-whisper transcription returned no text.")

        return TranscriptionResult(provider=self.provider_name, text=transcript_text)


def get_transcription_provider(application_settings: Settings = settings) -> BaseTranscriptionProvider:
    """Return the configured speech-to-text provider."""

    if application_settings.transcription_provider == "mock":
        return MockTranscriptionProvider()

    if application_settings.transcription_provider == "faster_whisper":
        return FasterWhisperTranscriptionProvider(application_settings)

    if application_settings.transcription_provider == "faster_whisper_remote":
        return RemoteFasterWhisperTranscriptionProvider(application_settings)

    if application_settings.transcription_provider == "disabled":
        return DisabledTranscriptionProvider()

    raise TranscriptionError(f"Unsupported transcription provider: {application_settings.transcription_provider}")
