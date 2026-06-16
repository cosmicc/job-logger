"""Environment-backed application configuration.

Every setting in this module is loaded from environment variables so Docker,
Cloudflare Tunnel, PostgreSQL, transcription, and Autotask deployments can be
configured without committing secrets to source control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_boolean(environment_variable_name: str, default_value: bool) -> bool:
    """Return a strict boolean value from an environment variable.

    The explicit parser avoids surprising truthiness rules where values such as
    "false" would otherwise be treated as true by Python.
    """

    raw_value = os.getenv(environment_variable_name)
    if raw_value is None or raw_value == "":
        return default_value

    normalized_value = raw_value.strip().lower()
    return normalized_value in {"1", "true", "yes", "y", "on"}


def _get_integer(environment_variable_name: str, default_value: int) -> int:
    """Return an integer setting with a clear fallback for empty variables."""

    raw_value = os.getenv(environment_variable_name)
    if raw_value is None or raw_value == "":
        return default_value

    return int(raw_value)


def _get_optional_integer(environment_variable_name: str) -> int | None:
    """Return an optional integer used by tenant-specific Autotask IDs."""

    raw_value = os.getenv(environment_variable_name)
    if raw_value is None or raw_value.strip() == "":
        return None

    return int(raw_value)


def _get_csv(environment_variable_name: str, default_value: str) -> list[str]:
    """Return a comma-separated setting as a clean list of values."""

    raw_value = os.getenv(environment_variable_name, default_value)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    # APP_ENV controls production-only safety checks and diagnostic verbosity.
    app_environment: str

    # APP_SECRET_KEY signs session cookies and CSRF state.
    app_secret_key: str

    # DATABASE_URL points SQLAlchemy at PostgreSQL in Docker or SQLite in tests.
    database_url: str

    # APP_USERNAME is the single local app account name.
    app_username: str

    # APP_PASSWORD is the password for the single local application account.
    # It must be provided through a secret environment file or secret store.
    app_password: str | None

    # APP_SESSION_COOKIE_SECURE should be true when served through HTTPS/Cloudflare.
    session_cookie_secure: bool

    # APP_ALLOWED_HOSTS limits accepted Host headers when configured.
    allowed_hosts: list[str]

    # CLOUDFLARE_ACCESS_REQUIRED optionally requires a Cloudflare Access identity header.
    cloudflare_access_required: bool

    # TRANSCRIPTION_PROVIDER selects the audio transcription backend.
    transcription_provider: str

    # MAX_AUDIO_UPLOAD_BYTES prevents memory exhaustion from oversized audio uploads.
    max_audio_upload_bytes: int

    # FASTER_WHISPER_MODEL is a local model size, Hugging Face model name, or local model path.
    faster_whisper_model: str

    # FASTER_WHISPER_DEVICE controls whether faster-whisper uses CPU, CUDA, or auto selection.
    faster_whisper_device: str

    # FASTER_WHISPER_COMPUTE_TYPE controls faster-whisper precision and memory use.
    faster_whisper_compute_type: str

    # FASTER_WHISPER_DOWNLOAD_ROOT stores local model files so Docker restarts do not redownload them.
    faster_whisper_download_root: str

    # FASTER_WHISPER_LOCAL_FILES_ONLY prevents model downloads when true.
    faster_whisper_local_files_only: bool

    # FASTER_WHISPER_LANGUAGE optionally pins transcription language, such as "en".
    faster_whisper_language: str | None

    # FASTER_WHISPER_BEAM_SIZE controls local decoding quality and CPU cost.
    faster_whisper_beam_size: int

    # FASTER_WHISPER_CPU_THREADS controls faster-whisper CPU worker threads.
    faster_whisper_cpu_threads: int

    # AUTOTASK_PROVIDER selects mock mode or the live Autotask REST client.
    autotask_provider: str

    # AUTOTASK_BASE_URL is the tenant-specific Autotask REST API base URL.
    autotask_base_url: str | None

    # AUTOTASK_USERNAME is the Autotask API user name header value.
    autotask_username: str | None

    # AUTOTASK_SECRET is the Autotask API secret header value.
    autotask_secret: str | None

    # AUTOTASK_API_INTEGRATION_CODE is the Autotask API tracking identifier.
    autotask_api_integration_code: str | None

    # AUTOTASK_RESOURCE_ID is the resource that owns created time entries.
    autotask_resource_id: int | None

    # AUTOTASK_ROLE_ID is the Autotask role for created ticket time entries.
    autotask_role_id: int | None

    # AUTOTASK_BILLING_CODE_ID optionally sets the work type/allocation code.
    autotask_billing_code_id: int | None

    # AUTOTASK_TIME_ENTRY_TYPE defaults to ticket time entry type 2.
    autotask_time_entry_type: int

    # AUTOTASK_IMPERSONATION_RESOURCE_ID optionally tells Autotask who is being impersonated.
    autotask_impersonation_resource_id: int | None

    # AUTOTASK_STATUS_* values map local review statuses to tenant picklist IDs.
    autotask_status_in_progress_id: int | None
    autotask_status_waiting_customer_id: int | None
    autotask_status_waiting_parts_id: int | None
    autotask_status_follow_up_id: int | None
    autotask_status_complete_id: int | None

    @property
    def is_production(self) -> bool:
        """Return whether production safety checks should be enforced."""

        return self.app_environment.lower() == "production"

    @property
    def autotask_status_id_map(self) -> dict[str, int]:
        """Return configured Autotask ticket-status picklist IDs."""

        status_mapping: dict[str, int] = {}
        if self.autotask_status_in_progress_id is not None:
            status_mapping["in_progress"] = self.autotask_status_in_progress_id
        if self.autotask_status_waiting_customer_id is not None:
            status_mapping["waiting_customer"] = self.autotask_status_waiting_customer_id
        if self.autotask_status_waiting_parts_id is not None:
            status_mapping["waiting_parts"] = self.autotask_status_waiting_parts_id
        if self.autotask_status_follow_up_id is not None:
            status_mapping["follow_up"] = self.autotask_status_follow_up_id
        if self.autotask_status_complete_id is not None:
            status_mapping["complete"] = self.autotask_status_complete_id
        return status_mapping


def load_settings() -> Settings:
    """Load application settings from the current process environment."""

    return Settings(
        app_environment=os.getenv("APP_ENV", "development"),
        app_secret_key=os.getenv("APP_SECRET_KEY", "development-only-change-me"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://job_logger:job_logger_password@db:5432/job_logger",
        ),
        app_username=os.getenv("APP_USERNAME", "admin"),
        app_password=os.getenv("APP_PASSWORD") or None,
        session_cookie_secure=_get_boolean("APP_SESSION_COOKIE_SECURE", False),
        allowed_hosts=_get_csv("APP_ALLOWED_HOSTS", "localhost,127.0.0.1,app"),
        cloudflare_access_required=_get_boolean("CLOUDFLARE_ACCESS_REQUIRED", False),
        transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "mock").strip().lower(),
        max_audio_upload_bytes=_get_integer("MAX_AUDIO_UPLOAD_BYTES", 10 * 1024 * 1024),
        faster_whisper_model=os.getenv("FASTER_WHISPER_MODEL", "base.en"),
        faster_whisper_device=os.getenv("FASTER_WHISPER_DEVICE", "cpu"),
        faster_whisper_compute_type=os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8"),
        faster_whisper_download_root=os.getenv("FASTER_WHISPER_DOWNLOAD_ROOT", "/models/faster-whisper"),
        faster_whisper_local_files_only=_get_boolean("FASTER_WHISPER_LOCAL_FILES_ONLY", False),
        faster_whisper_language=os.getenv("FASTER_WHISPER_LANGUAGE") or "en",
        faster_whisper_beam_size=_get_integer("FASTER_WHISPER_BEAM_SIZE", 5),
        faster_whisper_cpu_threads=_get_integer("FASTER_WHISPER_CPU_THREADS", 8),
        autotask_provider=os.getenv("AUTOTASK_PROVIDER", "mock").strip().lower(),
        autotask_base_url=os.getenv("AUTOTASK_BASE_URL") or None,
        autotask_username=os.getenv("AUTOTASK_USERNAME") or None,
        autotask_secret=os.getenv("AUTOTASK_SECRET") or None,
        autotask_api_integration_code=os.getenv("AUTOTASK_API_INTEGRATION_CODE") or None,
        autotask_resource_id=_get_optional_integer("AUTOTASK_RESOURCE_ID"),
        autotask_role_id=_get_optional_integer("AUTOTASK_ROLE_ID"),
        autotask_billing_code_id=_get_optional_integer("AUTOTASK_BILLING_CODE_ID"),
        autotask_time_entry_type=_get_integer("AUTOTASK_TIME_ENTRY_TYPE", 2),
        autotask_impersonation_resource_id=_get_optional_integer("AUTOTASK_IMPERSONATION_RESOURCE_ID"),
        autotask_status_in_progress_id=_get_optional_integer("AUTOTASK_STATUS_IN_PROGRESS_ID"),
        autotask_status_waiting_customer_id=_get_optional_integer("AUTOTASK_STATUS_WAITING_CUSTOMER_ID"),
        autotask_status_waiting_parts_id=_get_optional_integer("AUTOTASK_STATUS_WAITING_PARTS_ID"),
        autotask_status_follow_up_id=_get_optional_integer("AUTOTASK_STATUS_FOLLOW_UP_ID"),
        autotask_status_complete_id=_get_optional_integer("AUTOTASK_STATUS_COMPLETE_ID"),
    )


settings = load_settings()
