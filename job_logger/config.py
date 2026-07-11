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
    "technical facts, customer impact, ticket context, and any leading "
    "'Remote. ' or 'On-Site. ' prefix. Improve grammar, punctuation, "
    "capitalization, and "
    "readability. Do not invent work, parts, durations, ticket numbers, root "
    "causes, customer approvals, or follow-up actions. Return only the cleaned "
    "summary text with no markdown, title, explanation, or surrounding quotes."
)

DEFAULT_AI_HELP_PROVIDER = "gemini"
DEFAULT_GEMINI_HELP_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_HELP_API_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
VALID_MAIL_MODES = {"smtp", "smtp2go"}


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


def _get_positive_integer(environment_variable_name: str, default_value: int) -> int:
    """Return a positive integer setting, failing fast for unsafe values."""

    value = _get_integer(environment_variable_name, default_value)
    if value <= 0:
        raise ValueError(f"{environment_variable_name} must be greater than zero.")
    return value


def _get_bounded_integer(environment_variable_name: str, default_value: int, *, minimum: int, maximum: int) -> int:
    """Return an integer constrained to an inclusive safe range."""

    value = _get_integer(environment_variable_name, default_value)
    if value < minimum or value > maximum:
        raise ValueError(f"{environment_variable_name} must be between {minimum} and {maximum}.")
    return value


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


def _get_nonnegative_float(environment_variable_name: str, default_value: float) -> float:
    """Return a non-negative float setting, failing fast for unsafe values."""

    value = _get_float(environment_variable_name, default_value)
    if value < 0:
        raise ValueError(f"{environment_variable_name} must be greater than or equal to zero.")
    return value


def _get_optional_integer(environment_variable_name: str) -> int | None:
    """Return an optional integer used by tenant-specific Autotask IDs."""

    raw_value = os.getenv(environment_variable_name)
    if raw_value is None or raw_value.strip() == "":
        return None

    return int(raw_value)


def _get_log_level() -> str:
    """Return the validated application stdout logging level."""

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if log_level not in VALID_LOG_LEVELS:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR.")
    return log_level


def _get_ai_cleanup_provider() -> str:
    """Return the normalized provider key used by the AI cleanup service."""

    normalized_provider = os.getenv("AI_CLEANUP_PROVIDER", "gemini").strip().lower().replace("-", "_")
    if normalized_provider == "lmstudio":
        return "lm_studio"

    return normalized_provider or "gemini"


def _get_mail_mode() -> str:
    """Return the validated mail delivery mode."""

    mail_mode = os.getenv("MAIL_MODE", "smtp").strip().lower().replace("-", "_") or "smtp"
    if mail_mode not in VALID_MAIL_MODES:
        raise ValueError("MAIL_MODE must be smtp or smtp2go.")
    return mail_mode


@dataclass(frozen=True)
class Settings:
    """Typed application settings loaded from environment variables."""

    # APP_ENV controls production-only safety checks and diagnostic verbosity.
    app_environment: str

    # DEV_BUILD marks a Docker/dev deployment with a visible yellow header badge.
    dev_build: bool

    # APP_SECRET_KEY signs session cookies and CSRF state.
    app_secret_key: str

    # DATABASE_URL points SQLAlchemy at PostgreSQL in Docker or SQLite in tests.
    database_url: str

    # DATABASE_CONNECT_TIMEOUT_SECONDS bounds new PostgreSQL TCP connection waits.
    database_connect_timeout_seconds: int

    # DATABASE_POOL_SIZE keeps a bounded pool of reusable PostgreSQL connections.
    database_pool_size: int

    # DATABASE_MAX_OVERFLOW allows short bursts above DATABASE_POOL_SIZE.
    database_max_overflow: int

    # DATABASE_POOL_TIMEOUT_SECONDS bounds how long requests wait for a pooled connection.
    database_pool_timeout_seconds: int

    # DATABASE_POOL_RECYCLE_SECONDS refreshes long-lived pooled connections.
    database_pool_recycle_seconds: int

    # DATABASE_UNAVAILABLE_CHECK_INTERVAL_SECONDS throttles limp-mode DB probes.
    database_unavailable_check_interval_seconds: int

    # APP_HEALTH_MONITOR_INTERVAL_SECONDS controls the background Pushover check cadence.
    app_health_monitor_interval_seconds: int

    # APP_HEALTH_DB_LATENCY_*_MS classify slow database probes for monitoring.
    app_health_db_latency_warning_ms: float
    app_health_db_latency_critical_ms: float

    # APP_HEALTH_DB_POOL_*_PERCENT classify high SQLAlchemy pool usage.
    app_health_db_pool_warning_percent: float
    app_health_db_pool_critical_percent: float

    # LOG_LEVEL controls how verbose stdout/stderr and optional file logs should be.
    log_level: str

    # LOG_DIR optionally enables a redacted app log file under the configured directory.
    log_dir: str | None

    # APP_USERNAME is the single local app account name.
    app_username: str

    # APP_PASSWORD is the password for the single local application account.
    # It must be provided through a secret environment file or secret store.
    app_password: str | None

    # ADMIN_CONTACT_EMAIL is the safe support contact shown to end users.
    admin_contact_email: str

    # APP_SESSION_COOKIE_SECURE should be true when served through HTTPS/Cloudflare.
    session_cookie_secure: bool

    # APP_SESSION_TIMEOUT_HOURS controls how long a local login remains valid.
    session_timeout_hours: float

    # CLOUDFLARE_ACCESS_REQUIRED optionally requires a Cloudflare Access identity header.
    cloudflare_access_required: bool

    # CLOUDFLARE_IP_BLOCKING_ENABLED gates app-managed Cloudflare IP Access Rule writes.
    cloudflare_ip_blocking_enabled: bool

    # CLOUDFLARE_API_TOKEN authorizes zone-level IP Access Rule changes.
    cloudflare_api_token: str

    # CLOUDFLARE_ZONE_ID selects the Cloudflare zone where app-managed blocks live.
    cloudflare_zone_id: str

    # CLOUDFLARE_IP_BLOCK_ALLOWLIST protects trusted IPs/CIDRs from auto/manual app blocks.
    cloudflare_ip_block_allowlist: str

    # CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS is the consecutive-failure threshold.
    cloudflare_auto_block_failed_login_attempts: int

    # LOGIN_LOCAL_LOCKOUT_MINUTES is the app-enforced lockout after the threshold.
    login_local_lockout_minutes: int

    # PASSWORD_RESET_ENABLED gates self-service managed-user password resets.
    password_reset_enabled: bool

    # PASSWORD_RESET_TOKEN_TTL_HOURS controls how long emailed reset links work.
    password_reset_token_ttl_hours: float

    # APP_PUBLIC_BASE_URL is the absolute HTTPS origin used in app-generated email links.
    app_public_base_url: str

    # MAIL_ENABLED gates app-generated account email delivery.
    mail_enabled: bool

    # MAIL_FROM_* controls the sender identity shown on app-generated email.
    mail_from_email: str
    mail_from_name: str

    # MAIL_MODE selects the delivery backend: smtp or smtp2go.
    mail_mode: str

    # MAIL_SMTP_* settings configure the generic SMTP transport.
    mail_smtp_host: str
    mail_smtp_port: int
    mail_smtp_username: str | None
    mail_smtp_password: str | None
    mail_smtp_starttls: bool
    mail_smtp_ssl: bool
    mail_smtp_timeout_seconds: float

    # MAIL_SMTP2GO_API_KEY authenticates SMTP2GO API email delivery.
    mail_smtp2go_api_key: str | None

    # TURNSTILE_* settings configure Cloudflare Turnstile verification for reset requests.
    turnstile_enabled: bool
    turnstile_site_key: str
    turnstile_secret_key: str
    turnstile_verify_url: str
    turnstile_timeout_seconds: float

    # PUSHOVER_ENABLED gates best-effort admin health notifications.
    pushover_enabled: bool

    # PUSHOVER_USER_KEY is the administrator or group key that receives alerts.
    pushover_user_key: str | None

    # PUSHOVER_APP_KEY is the Pushover application API token.
    pushover_app_key: str | None

    # PUSHOVER_API_URL is the message endpoint, overrideable for tests/proxies.
    pushover_api_url: str

    # PUSHOVER_TIMEOUT_SECONDS bounds notification delivery attempts.
    pushover_timeout_seconds: float

    # TRANSCRIPTION_PROVIDER selects the audio transcription backend.
    transcription_provider: str

    # MAX_AUDIO_UPLOAD_BYTES prevents memory exhaustion from oversized audio uploads.
    max_audio_upload_bytes: int

    # MAX_BACKUP_RESTORE_BYTES bounds full-data restore uploads on /debug.
    max_backup_restore_bytes: int

    # AUTOMATIC_BACKUPS_ENABLED controls the hourly full-database backup task.
    automatic_backups_enabled: bool

    # AUTOMATIC_BACKUP_DIR stores hourly and daily backup files.
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

    # FASTER_WHISPER_REMOTE_URL is the exact multipart transcription endpoint
    # used when TRANSCRIPTION_PROVIDER=faster_whisper_remote.
    faster_whisper_remote_url: str

    # FASTER_WHISPER_REMOTE_API_KEY is sent as a bearer token when configured.
    faster_whisper_remote_api_key: str | None

    # FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS bounds remote transcription latency.
    faster_whisper_remote_timeout_seconds: float

    # AI_CLEANUP_ENABLED gates external summary cleanup calls.
    ai_cleanup_enabled: bool

    # AI_CLEANUP_PROVIDER selects the cleanup backend: gemini, grok, ollama, or lm_studio.
    ai_cleanup_provider: str

    # GEMINI_API_KEY authorizes Google Gemini cleanup requests.
    gemini_api_key: str | None

    # GEMINI_CLEANUP_MODEL selects the Gemini model used for text cleanup.
    gemini_cleanup_model: str

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

    # AI_CLEANUP_REVERT_RETENTION_HOURS limits how long pre-cleanup text is retained for undo.
    ai_cleanup_revert_retention_hours: float

    # AI_HELP_ENABLED gates provider-backed end-user help answers.
    ai_help_enabled: bool

    # AI_HELP_PROVIDER selects the help backend. Gemini is currently supported.
    ai_help_provider: str

    # GEMINI_MODEL selects the Gemini model used for help answers.
    gemini_model: str

    # GEMINI_API_BASE is the Gemini OpenAI-compatible API base URL.
    gemini_api_base: str

    # AI_HELP_MAX_TOKENS limits generated help-answer length.
    ai_help_max_tokens: int

    # AI_HELP_TEMPERATURE controls help-answer determinism.
    ai_help_temperature: float

    # AI_HELP_INSTRUCTIONS stores the server-side support prompt for help answers.
    ai_help_instructions: str

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

    # AUTOTASK_MAX_CONCURRENT_REQUESTS caps live REST calls below Autotask's thread threshold.
    autotask_max_concurrent_requests: int

    # AUTOTASK_REQUEST_SLOT_TIMEOUT_SECONDS bounds waits for a limiter slot.
    autotask_request_slot_timeout_seconds: float

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

    @property
    def password_reset_token_ttl_seconds(self) -> int:
        """Return the password-reset token lifetime as whole seconds."""

        return max(int(self.password_reset_token_ttl_hours * 60 * 60), 1)

    @property
    def mail_delivery_configured(self) -> bool:
        """Return whether the selected mail mode can send app-generated email."""

        if not self.mail_enabled or not self.mail_from_email:
            return False
        if self.mail_mode == "smtp2go":
            return bool(self.mail_smtp2go_api_key)
        return bool(self.mail_smtp_host and self.mail_smtp_port > 0)

    @property
    def password_reset_mail_configured(self) -> bool:
        """Return whether the selected mail mode can send reset mail."""

        return self.mail_delivery_configured

    @property
    def pushover_configured(self) -> bool:
        """Return whether Pushover has the secrets needed to send messages."""

        return bool(self.pushover_user_key and self.pushover_app_key)

    @property
    def pushover_notifications_enabled(self) -> bool:
        """Return whether this runtime may send Pushover notifications."""

        return self.pushover_enabled and not self.dev_build

    @property
    def ai_help_configured(self) -> bool:
        """Return whether the help assistant has the secret settings it needs."""

        return bool(
            self.ai_help_enabled
            and self.ai_help_provider == "gemini"
            and self.gemini_api_key
            and self.ai_help_instructions.strip()
        )


def load_settings() -> Settings:
    """Load application settings from the current process environment."""

    return Settings(
        app_environment=os.getenv("APP_ENV", "development"),
        dev_build=_get_boolean("DEV_BUILD", False),
        app_secret_key=os.getenv("APP_SECRET_KEY", "development-only-change-me"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://job_logger:job_logger_password@db:5432/job_logger",
        ),
        database_connect_timeout_seconds=_get_positive_integer("DATABASE_CONNECT_TIMEOUT_SECONDS", 5),
        database_pool_size=_get_positive_integer("DATABASE_POOL_SIZE", 5),
        database_max_overflow=_get_integer("DATABASE_MAX_OVERFLOW", 10),
        database_pool_timeout_seconds=_get_positive_integer("DATABASE_POOL_TIMEOUT_SECONDS", 30),
        database_pool_recycle_seconds=_get_positive_integer("DATABASE_POOL_RECYCLE_SECONDS", 1800),
        database_unavailable_check_interval_seconds=_get_positive_integer(
            "DATABASE_UNAVAILABLE_CHECK_INTERVAL_SECONDS",
            5,
        ),
        app_health_monitor_interval_seconds=_get_positive_integer("APP_HEALTH_MONITOR_INTERVAL_SECONDS", 300),
        app_health_db_latency_warning_ms=_get_positive_float("APP_HEALTH_DB_LATENCY_WARNING_MS", 250.0),
        app_health_db_latency_critical_ms=_get_positive_float("APP_HEALTH_DB_LATENCY_CRITICAL_MS", 1000.0),
        app_health_db_pool_warning_percent=_get_positive_float("APP_HEALTH_DB_POOL_WARNING_PERCENT", 80.0),
        app_health_db_pool_critical_percent=_get_positive_float("APP_HEALTH_DB_POOL_CRITICAL_PERCENT", 95.0),
        log_level=_get_log_level(),
        log_dir=(os.getenv("LOG_DIR") or "").strip() or None,
        app_username=os.getenv("APP_USERNAME", "admin"),
        app_password=os.getenv("APP_PASSWORD") or None,
        admin_contact_email=(os.getenv("ADMIN_CONTACT_EMAIL") or "").strip(),
        session_cookie_secure=_get_boolean("APP_SESSION_COOKIE_SECURE", False),
        session_timeout_hours=_get_positive_float("APP_SESSION_TIMEOUT_HOURS", 12.0),
        cloudflare_access_required=_get_boolean("CLOUDFLARE_ACCESS_REQUIRED", False),
        cloudflare_ip_blocking_enabled=_get_boolean("CLOUDFLARE_IP_BLOCKING_ENABLED", False),
        cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN", ""),
        cloudflare_zone_id=os.getenv("CLOUDFLARE_ZONE_ID", ""),
        cloudflare_ip_block_allowlist=os.getenv("CLOUDFLARE_IP_BLOCK_ALLOWLIST", ""),
        cloudflare_auto_block_failed_login_attempts=_get_positive_integer(
            "CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS",
            5,
        ),
        login_local_lockout_minutes=_get_positive_integer("LOGIN_LOCAL_LOCKOUT_MINUTES", 15),
        password_reset_enabled=_get_boolean("PASSWORD_RESET_ENABLED", False),
        password_reset_token_ttl_hours=_get_positive_float("PASSWORD_RESET_TOKEN_TTL_HOURS", 24.0),
        app_public_base_url=(os.getenv("APP_PUBLIC_BASE_URL") or "").strip().rstrip("/"),
        mail_enabled=_get_boolean("MAIL_ENABLED", False),
        mail_from_email=(os.getenv("MAIL_FROM_EMAIL", "joblogger@example.com").strip() or "joblogger@example.com"),
        mail_from_name=(os.getenv("MAIL_FROM_NAME", "Job Logger").strip() or "Job Logger"),
        mail_mode=_get_mail_mode(),
        mail_smtp_host=(os.getenv("MAIL_SMTP_HOST") or "").strip(),
        mail_smtp_port=_get_positive_integer("MAIL_SMTP_PORT", 587),
        mail_smtp_username=(os.getenv("MAIL_SMTP_USERNAME") or "").strip() or None,
        mail_smtp_password=(os.getenv("MAIL_SMTP_PASSWORD") or "").strip() or None,
        mail_smtp_starttls=_get_boolean("MAIL_SMTP_STARTTLS", True),
        mail_smtp_ssl=_get_boolean("MAIL_SMTP_SSL", False),
        mail_smtp_timeout_seconds=_get_positive_float("MAIL_SMTP_TIMEOUT_SECONDS", 10.0),
        mail_smtp2go_api_key=(os.getenv("MAIL_SMTP2GO_API_KEY") or "").strip() or None,
        turnstile_enabled=_get_boolean("TURNSTILE_ENABLED", True),
        turnstile_site_key=(os.getenv("TURNSTILE_SITE_KEY") or "").strip(),
        turnstile_secret_key=(os.getenv("TURNSTILE_SECRET_KEY") or "").strip(),
        turnstile_verify_url=(
            os.getenv("TURNSTILE_VERIFY_URL", "https://challenges.cloudflare.com/turnstile/v0/siteverify").strip()
            or "https://challenges.cloudflare.com/turnstile/v0/siteverify"
        ),
        turnstile_timeout_seconds=_get_positive_float("TURNSTILE_TIMEOUT_SECONDS", 10.0),
        pushover_enabled=_get_boolean("PUSHOVER_ENABLED", False),
        pushover_user_key=(os.getenv("PUSHOVER_USER_KEY") or "").strip() or None,
        pushover_app_key=(os.getenv("PUSHOVER_APP_KEY") or "").strip() or None,
        pushover_api_url=(
            os.getenv("PUSHOVER_API_URL", "https://api.pushover.net/1/messages.json").strip()
            or "https://api.pushover.net/1/messages.json"
        ),
        pushover_timeout_seconds=_get_positive_float("PUSHOVER_TIMEOUT_SECONDS", 10.0),
        transcription_provider=os.getenv("TRANSCRIPTION_PROVIDER", "mock").strip().lower().replace("-", "_"),
        max_audio_upload_bytes=_get_integer("MAX_AUDIO_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_backup_restore_bytes=_get_integer("MAX_BACKUP_RESTORE_BYTES", 250 * 1024 * 1024),
        automatic_backups_enabled=_get_boolean("AUTOMATIC_BACKUPS_ENABLED", True),
        automatic_backup_dir=os.getenv(
            "AUTOMATIC_BACKUP_DIR",
            "backups",
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
        faster_whisper_remote_url=os.getenv("FASTER_WHISPER_REMOTE_URL", "").strip().rstrip("/"),
        faster_whisper_remote_api_key=os.getenv("FASTER_WHISPER_REMOTE_API_KEY") or None,
        faster_whisper_remote_timeout_seconds=_get_positive_float("FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS", 120.0),
        ai_cleanup_enabled=_get_boolean("AI_CLEANUP_ENABLED", False),
        ai_cleanup_provider=_get_ai_cleanup_provider(),
        gemini_api_key=(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip() or None,
        gemini_cleanup_model=os.getenv("GEMINI_CLEANUP_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash",
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
        ai_cleanup_revert_retention_hours=_get_positive_float("AI_CLEANUP_REVERT_RETENTION_HOURS", 24.0),
        ai_help_enabled=_get_boolean("AI_HELP_ENABLED", False),
        ai_help_provider=(
            os.getenv("AI_HELP_PROVIDER", DEFAULT_AI_HELP_PROVIDER).strip().lower().replace("-", "_")
            or DEFAULT_AI_HELP_PROVIDER
        ),
        gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_HELP_MODEL).strip() or DEFAULT_GEMINI_HELP_MODEL,
        gemini_api_base=(
            os.getenv("GEMINI_API_BASE", DEFAULT_GEMINI_HELP_API_BASE).strip().rstrip("/")
            or DEFAULT_GEMINI_HELP_API_BASE
        ),
        ai_help_max_tokens=_get_positive_integer("AI_HELP_MAX_TOKENS", 800),
        ai_help_temperature=_get_nonnegative_float("AI_HELP_TEMPERATURE", 0.2),
        ai_help_instructions=os.getenv("AI_HELP_INSTRUCTIONS", "").strip(),
        autotask_provider=os.getenv("AUTOTASK_PROVIDER", "autotask").strip().lower(),
        autotask_base_url=os.getenv("AUTOTASK_BASE_URL") or None,
        autotask_username=os.getenv("AUTOTASK_USERNAME") or None,
        autotask_secret=os.getenv("AUTOTASK_SECRET") or None,
        autotask_api_integration_code=os.getenv("AUTOTASK_API_INTEGRATION_CODE") or None,
        autotask_time_entry_type=_get_integer("AUTOTASK_TIME_ENTRY_TYPE", 2),
        autotask_max_concurrent_requests=_get_bounded_integer(
            "AUTOTASK_MAX_CONCURRENT_REQUESTS",
            2,
            minimum=1,
            maximum=3,
        ),
        autotask_request_slot_timeout_seconds=_get_positive_float("AUTOTASK_REQUEST_SLOT_TIMEOUT_SECONDS", 30.0),
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
