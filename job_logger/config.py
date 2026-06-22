"""Environment-backed application configuration.

Every setting in this module is loaded from environment variables so Docker,
Cloudflare Tunnel, PostgreSQL, transcription, and Autotask deployments can be
configured without committing secrets to source control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_FASTER_WHISPER_INITIAL_PROMPT = (
    "Use normal written punctuation. When spoken punctuation words such as "
    "comma, period, question mark, exclamation point, colon, semicolon, dash, "
    "or new paragraph are heard, render punctuation marks and paragraph breaks "
    "instead of spelling those words."
)

DEFAULT_AI_CLEANUP_INSTRUCTIONS = (
    "Clean up MSP work-summary notes for an Autotask time entry. Preserve the "
    "technical facts, customer impact, ticket context, and any leading Remote "
    "or On-Site prefix. Improve grammar, punctuation, capitalization, and "
    "readability. Do not invent work, parts, durations, ticket numbers, root "
    "causes, customer approvals, or follow-up actions. Return only the cleaned "
    "summary text with no markdown, title, explanation, or surrounding quotes."
)


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


def _get_float(environment_variable_name: str, default_value: float) -> float:
    """Return a float setting with a clear fallback for empty variables."""

    raw_value = os.getenv(environment_variable_name)
    if raw_value is None or raw_value == "":
        return default_value

    return float(raw_value)


def _get_positive_float(environment_variable_name: str, default_value: float) -> float:
    """Return a positive float setting, failing fast for unsafe values."""

    value = _get_float(environment_variable_name, default_value)
    if value <= 0:
        raise ValueError(f"{environment_variable_name} must be greater than zero.")
    return value


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


def _get_ai_cleanup_provider() -> str:
    """Return the normalized provider key used by the AI cleanup service."""

    normalized_provider = os.getenv("AI_CLEANUP_PROVIDER", "gemini").strip().lower().replace("-", "_")
    if normalized_provider == "lmstudio":
        return "lm_studio"

    return normalized_provider or "gemini"


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    # APP_ENV controls production-only safety checks and diagnostic verbosity.
    app_environment: str

    # APP_SECRET_KEY signs session cookies and CSRF state.
    app_secret_key: str

    # DATABASE_URL points SQLAlchemy at PostgreSQL in Docker or SQLite in tests.
    database_url: str

    # LOG_DIR stores host-mounted runtime logs inside the app container.
    log_dir: str

    # APP_USERNAME is the single local app account name.
    app_username: str

    # APP_PASSWORD is the password for the single local application account.
    # It must be provided through a secret environment file or secret store.
    app_password: str | None

    # LOGIN_FAILURE_LOG_PATH is a JSONL file for failed app-login attempts.
    # It should live in a host-mounted log directory for Docker deployments.
    login_failure_log_path: str

    # LOGIN_SUCCESS_LOG_PATH is a JSONL file for successful app-login attempts.
    # It should live in a host-mounted log directory for Docker deployments.
    login_success_log_path: str

    # LOGIN_FAILURE_DEBUG_ROWS limits failed-login rows shown on /debug.
    login_failure_debug_rows: int

    # APP_SESSION_COOKIE_SECURE should be true when served through HTTPS/Cloudflare.
    session_cookie_secure: bool

    # APP_SESSION_TIMEOUT_HOURS controls how long a local login remains valid.
    session_timeout_hours: float

    # APP_ALLOWED_HOSTS limits accepted Host headers when configured.
    allowed_hosts: list[str]

    # CLOUDFLARE_ACCESS_REQUIRED optionally requires a Cloudflare Access identity header.
    cloudflare_access_required: bool

    # TRANSCRIPTION_PROVIDER selects the audio transcription backend.
    transcription_provider: str

    # MAX_AUDIO_UPLOAD_BYTES prevents memory exhaustion from oversized audio uploads.
    max_audio_upload_bytes: int

    # MAX_BACKUP_RESTORE_BYTES bounds full-data restore uploads on /debug.
    max_backup_restore_bytes: int

    # AUTOMATIC_BACKUPS_ENABLED controls the hourly full-database backup task.
    automatic_backups_enabled: bool

    # AUTOMATIC_BACKUP_DIR stores host-mounted hourly and daily backup files.
    automatic_backup_dir: str

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

    # FASTER_WHISPER_INITIAL_PROMPT guides local transcription formatting.
    faster_whisper_initial_prompt: str | None

    # AI_CLEANUP_ENABLED gates external summary cleanup calls.
    ai_cleanup_enabled: bool

    # AI_CLEANUP_PROVIDER selects the cleanup backend: gemini, grok, ollama, or lm_studio.
    ai_cleanup_provider: str

    # GEMINI_API_KEY authorizes Google Gemini cleanup requests.
    gemini_api_key: str | None

    # GEMINI_CLEANUP_MODEL selects the Gemini model used for text cleanup.
    gemini_cleanup_model: str

    # GEMINI_CLEANUP_API_BASE_URL supports Gemini API endpoint overrides.
    gemini_cleanup_api_base_url: str

    # GROQ_API_KEY authorizes GroqCloud cleanup requests. The user-facing provider
    # value remains "grok" for compatibility with the requested spelling.
    groq_api_key: str | None

    # GROQ_CLEANUP_MODEL selects the Groq-hosted model used for text cleanup.
    groq_cleanup_model: str

    # GROQ_CLEANUP_API_BASE_URL supports Groq endpoint overrides.
    groq_cleanup_api_base_url: str

    # OLLAMA_CLEANUP_MODEL selects the locally installed Ollama model used for cleanup.
    ollama_cleanup_model: str

    # OLLAMA_CLEANUP_API_BASE_URL points at a loopback or private-network Ollama API base URL.
    ollama_cleanup_api_base_url: str

    # LM_STUDIO_CLEANUP_MODEL selects the loaded LM Studio model identifier used for cleanup.
    lm_studio_cleanup_model: str

    # LM_STUDIO_CLEANUP_API_BASE_URL points at a loopback or private-network LM Studio OpenAI-compatible base URL.
    lm_studio_cleanup_api_base_url: str

    # LM_STUDIO_API_KEY is optional and only used if the local LM Studio server requires one.
    lm_studio_api_key: str | None

    # AI_CLEANUP_INSTRUCTIONS stores the server-side cleanup prompt.
    ai_cleanup_instructions: str

    # AI_CLEANUP_TIMEOUT_SECONDS bounds cleanup latency from the UI.
    ai_cleanup_timeout_seconds: float

    # AI_CLEANUP_MAX_INPUT_CHARS limits user text sent to the selected provider.
    ai_cleanup_max_input_chars: int

    # AUTOTASK_PROVIDER selects the live Autotask REST client; mock is for tests/development only.
    autotask_provider: str

    # AUTOTASK_BASE_URL is the tenant-specific Autotask REST API base URL.
    autotask_base_url: str | None

    # AUTOTASK_USERNAME is the Autotask API user name header value.
    autotask_username: str | None

    # AUTOTASK_SECRET is the Autotask API secret header value.
    autotask_secret: str | None

    # AUTOTASK_API_INTEGRATION_CODE is the Autotask API tracking identifier.
    autotask_api_integration_code: str | None

    # AUTOTASK_TIME_ENTRY_TYPE defaults to ticket time entry type 2.
    autotask_time_entry_type: int

    # AUTOTASK_TICKET_STATUS_UPDATES_ENABLED allows the app to PATCH Tickets.status.
    # Keep this opt-in because TimeEntries can usually be created without ticket
    # status writes, and many API security levels grant time-entry permissions
    # separately from ticket workflow/status mutation permissions.
    autotask_ticket_status_updates_enabled: bool

    # AUTOTASK_STATUS_* values map local review statuses to tenant picklist IDs.
    autotask_status_in_progress_id: int | None
    autotask_status_waiting_customer_id: int | None
    autotask_status_waiting_parts_id: int | None
    autotask_status_follow_up_id: int | None
    autotask_status_complete_id: int | None

    # WEBAUTHN_RP_NAME is the browser-facing passkey relying-party label.
    webauthn_rp_name: str

    # WEBAUTHN_RP_ID optionally pins the passkey relying-party domain.
    webauthn_rp_id: str | None

    # WEBAUTHN_ORIGIN optionally pins the expected browser origin for passkeys.
    webauthn_origin: str | None

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

    @property
    def session_timeout_seconds(self) -> int:
        """Return the configured session timeout as whole seconds."""

        return max(int(self.session_timeout_hours * 60 * 60), 1)


def load_settings() -> Settings:
    """Load application settings from the current process environment."""

    return Settings(
        app_environment=os.getenv("APP_ENV", "development"),
        app_secret_key=os.getenv("APP_SECRET_KEY", "development-only-change-me"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://job_logger:job_logger_password@db:5432/job_logger",
        ),
        log_dir=os.getenv("LOG_DIR", "logs"),
        app_username=os.getenv("APP_USERNAME", "admin"),
        app_password=os.getenv("APP_PASSWORD") or None,
        login_failure_log_path=os.getenv(
            "LOGIN_FAILURE_LOG_PATH",
            f"{os.getenv('LOG_DIR', 'logs').rstrip('/')}/job-logger-login-failures.log",
        ),
        login_success_log_path=os.getenv(
            "LOGIN_SUCCESS_LOG_PATH",
            f"{os.getenv('LOG_DIR', 'logs').rstrip('/')}/job-logger-login-successes.log",
        ),
        login_failure_debug_rows=_get_integer("LOGIN_FAILURE_DEBUG_ROWS", 200),
        session_cookie_secure=_get_boolean("APP_SESSION_COOKIE_SECURE", False),
        session_timeout_hours=_get_positive_float("APP_SESSION_TIMEOUT_HOURS", 12.0),
        allowed_hosts=_get_csv("APP_ALLOWED_HOSTS", "localhost,127.0.0.1,app"),
        cloudflare_access_required=_get_boolean("CLOUDFLARE_ACCESS_REQUIRED", False),
        transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "mock").strip().lower(),
        max_audio_upload_bytes=_get_integer("MAX_AUDIO_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_backup_restore_bytes=_get_integer("MAX_BACKUP_RESTORE_BYTES", 250 * 1024 * 1024),
        automatic_backups_enabled=_get_boolean("AUTOMATIC_BACKUPS_ENABLED", True),
        automatic_backup_dir=os.getenv(
            "AUTOMATIC_BACKUP_DIR",
            f"{os.getenv('LOG_DIR', 'logs').rstrip('/')}/backups",
        ),
        faster_whisper_model=os.getenv("FASTER_WHISPER_MODEL", "base.en"),
        faster_whisper_device=os.getenv("FASTER_WHISPER_DEVICE", "cpu"),
        faster_whisper_compute_type=os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8"),
        faster_whisper_download_root=os.getenv("FASTER_WHISPER_DOWNLOAD_ROOT", "/models/faster-whisper"),
        faster_whisper_local_files_only=_get_boolean("FASTER_WHISPER_LOCAL_FILES_ONLY", False),
        faster_whisper_language=os.getenv("FASTER_WHISPER_LANGUAGE") or "en",
        faster_whisper_beam_size=_get_integer("FASTER_WHISPER_BEAM_SIZE", 5),
        faster_whisper_cpu_threads=_get_integer("FASTER_WHISPER_CPU_THREADS", 8),
        faster_whisper_initial_prompt=(
            os.getenv("FASTER_WHISPER_INITIAL_PROMPT", DEFAULT_FASTER_WHISPER_INITIAL_PROMPT).strip() or None
        ),
        ai_cleanup_enabled=_get_boolean("AI_CLEANUP_ENABLED", False),
        ai_cleanup_provider=_get_ai_cleanup_provider(),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None,
        gemini_cleanup_model=os.getenv("GEMINI_CLEANUP_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash",
        gemini_cleanup_api_base_url=os.getenv(
            "GEMINI_CLEANUP_API_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ).rstrip("/"),
        groq_api_key=os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY") or None,
        groq_cleanup_model=(
            os.getenv("GROQ_CLEANUP_MODEL")
            or os.getenv("GROK_CLEANUP_MODEL")
            or "llama-3.1-8b-instant"
        ).strip()
        or "llama-3.1-8b-instant",
        groq_cleanup_api_base_url=(
            os.getenv("GROQ_CLEANUP_API_BASE_URL")
            or os.getenv("GROK_CLEANUP_API_BASE_URL")
            or "https://api.groq.com/openai/v1"
        ).rstrip("/"),
        ollama_cleanup_model=os.getenv("OLLAMA_CLEANUP_MODEL", "llama3.1").strip() or "llama3.1",
        ollama_cleanup_api_base_url=os.getenv(
            "OLLAMA_CLEANUP_API_BASE_URL",
            "http://127.0.0.1:11434/api",
        ).rstrip("/"),
        lm_studio_cleanup_model=os.getenv("LM_STUDIO_CLEANUP_MODEL", "local-model").strip() or "local-model",
        lm_studio_cleanup_api_base_url=os.getenv(
            "LM_STUDIO_CLEANUP_API_BASE_URL",
            "http://127.0.0.1:1234/v1",
        ).rstrip("/"),
        lm_studio_api_key=os.getenv("LM_STUDIO_API_KEY") or None,
        ai_cleanup_instructions=(
            os.getenv("AI_CLEANUP_INSTRUCTIONS", DEFAULT_AI_CLEANUP_INSTRUCTIONS).strip()
            or DEFAULT_AI_CLEANUP_INSTRUCTIONS
        ),
        ai_cleanup_timeout_seconds=_get_float("AI_CLEANUP_TIMEOUT_SECONDS", 20.0),
        ai_cleanup_max_input_chars=_get_integer("AI_CLEANUP_MAX_INPUT_CHARS", 12000),
        autotask_provider=os.getenv("AUTOTASK_PROVIDER", "autotask").strip().lower(),
        autotask_base_url=os.getenv("AUTOTASK_BASE_URL") or None,
        autotask_username=os.getenv("AUTOTASK_USERNAME") or None,
        autotask_secret=os.getenv("AUTOTASK_SECRET") or None,
        autotask_api_integration_code=os.getenv("AUTOTASK_API_INTEGRATION_CODE") or None,
        autotask_time_entry_type=_get_integer("AUTOTASK_TIME_ENTRY_TYPE", 2),
        autotask_ticket_status_updates_enabled=_get_boolean("AUTOTASK_TICKET_STATUS_UPDATES_ENABLED", False),
        autotask_status_in_progress_id=_get_optional_integer("AUTOTASK_STATUS_IN_PROGRESS_ID"),
        autotask_status_waiting_customer_id=_get_optional_integer("AUTOTASK_STATUS_WAITING_CUSTOMER_ID"),
        autotask_status_waiting_parts_id=_get_optional_integer("AUTOTASK_STATUS_WAITING_PARTS_ID"),
        autotask_status_follow_up_id=_get_optional_integer("AUTOTASK_STATUS_FOLLOW_UP_ID"),
        autotask_status_complete_id=_get_optional_integer("AUTOTASK_STATUS_COMPLETE_ID"),
        webauthn_rp_name=os.getenv("WEBAUTHN_RP_NAME", "Job Logger").strip() or "Job Logger",
        webauthn_rp_id=(os.getenv("WEBAUTHN_RP_ID") or "").strip() or None,
        webauthn_origin=(os.getenv("WEBAUTHN_ORIGIN") or "").strip().rstrip("/") or None,
    )


settings = load_settings()
