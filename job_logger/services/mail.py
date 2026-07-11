"""Mail delivery helpers for Job Logger account workflows."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlparse

import httpx

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text

LOGGER = logging.getLogger(__name__)
MAX_SAFE_MAIL_ERROR_LENGTH = 500
PASSWORD_RESET_SUBJECT = "Reset your Job Logger password"
WELCOME_EMAIL_SUBJECT = "Welcome to Job Logger"
SMTP2GO_EMAIL_SEND_URL = "https://api.smtp2go.com/v3/email/send"


@dataclass(frozen=True)
class MailDeliveryResult:
    """Safe outcome returned after attempting app-generated mail delivery."""

    succeeded: bool
    provider: str = "smtp"
    safe_error: str | None = None


def _safe_mail_error(exc: Exception) -> str:
    """Return a bounded, redacted mail error for audit and diagnostics."""

    error_text = f"{exc.__class__.__name__}: {exc}"
    return redact_sensitive_text(error_text.replace("\r", "\\r").replace("\n", "\\n"))[:MAX_SAFE_MAIL_ERROR_LENGTH]


def _sender_address(application_settings: Settings) -> str:
    """Return the formatted From header for app-generated email."""

    return formataddr((application_settings.mail_from_name, application_settings.mail_from_email))


def _password_reset_body(*, reset_url: str, application_settings: Settings) -> str:
    """Return the plain-text password-reset email body."""

    return (
        "A password reset was requested for your Job Logger account.\n\n"
        f"Reset your password using this link:\n{reset_url}\n\n"
        f"This link is valid for {int(application_settings.password_reset_token_ttl_hours)} hours and can be used only once.\n\n"
        "If you did not request this reset, you can ignore this email."
    )


def _first_name_from_full_name(*, full_name: str, fallback_username: str) -> str:
    """Return the first display-name token for a welcome greeting."""

    stripped_name = full_name.strip()
    if stripped_name:
        return stripped_name.split()[0]
    stripped_username = fallback_username.strip()
    return stripped_username or "there"


def _welcome_contact_line(admin_contact_email: str) -> str:
    """Return the final welcome-email support line."""

    stripped_email = admin_contact_email.strip()
    if stripped_email:
        return f"If you need help, contact {stripped_email}."
    return "If you need help, contact your app administrator."


def build_welcome_email_body(
    *,
    full_name: str,
    username: str,
    app_url: str,
    admin_contact_email: str,
) -> str:
    """Return the plain-text welcome email body for a new managed web user."""

    first_name = _first_name_from_full_name(full_name=full_name, fallback_username=username)
    return (
        f"{first_name},\n\n"
        "You have been invited to use Job Logger for recording Autotask time entries, "
        "reviewing Autotask ticket notes, and submitting approved work to Autotask.\n\n"
        "Open Job Logger here:\n"
        f"{app_url}\n\n"
        "Sign in with your username:\n"
        f"{username.strip()}\n\n"
        "Use the temporary password provided by your administrator. After you sign in, "
        "Job Logger will ask you to create a new password before continuing.\n\n"
        "Job Logger can be used from a web browser on a computer or installed on your mobile device. "
        'After you log in, you can set up "Device sign-in", which will allow you to log in to the app '
        "quickly with your mobile device unlock, such as a fingerprint, without needing to type in your "
        "username and password each time.\n\n"
        "To install Job Logger on your phone:\n\n"
        "iPhone or iPad:\n"
        "1. Open the Job Logger link in Safari.\n"
        "2. Tap the Share button.\n"
        "3. Tap Add to Home Screen.\n"
        "4. Tap Add.\n\n"
        "Android:\n"
        "1. Open the Job Logger link in Chrome.\n"
        "2. Tap the browser menu.\n"
        "3. Tap Add to Home screen or Install app.\n"
        "4. Follow the prompt to add it.\n\n"
        f"{_welcome_contact_line(admin_contact_email)}"
    )


def _mail_not_configured_result(application_settings: Settings) -> MailDeliveryResult:
    """Return a consistent failure when the selected mail transport is incomplete."""

    return MailDeliveryResult(
        succeeded=False,
        provider=application_settings.mail_mode,
        safe_error=f"{application_settings.mail_mode} mail is not configured.",
    )


def _smtp2go_response_error(response: httpx.Response) -> str:
    """Return a bounded, redacted SMTP2GO API error summary."""

    try:
        payload = response.json()
    except ValueError:
        return redact_sensitive_text(f"SMTP2GO HTTP {response.status_code}: {response.text}")[:MAX_SAFE_MAIL_ERROR_LENGTH]

    error_payload = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(error_payload, dict):
        error_code = str(error_payload.get("error_code") or "").strip()
        error_message = str(error_payload.get("error") or "").strip()
        if error_code or error_message:
            return redact_sensitive_text(
                f"SMTP2GO HTTP {response.status_code}: {error_code} {error_message}".strip()
            )[:MAX_SAFE_MAIL_ERROR_LENGTH]
    return redact_sensitive_text(f"SMTP2GO HTTP {response.status_code}: {payload}")[:MAX_SAFE_MAIL_ERROR_LENGTH]


def _smtp2go_delivery_count(response_data: dict[str, object], field_name: str) -> int:
    """Return a non-negative SMTP2GO delivery counter from a response data field."""

    raw_value = response_data.get(field_name)
    if raw_value is None:
        return 0
    try:
        parsed_value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(parsed_value, 0)


def send_password_reset_email(
    *,
    recipient_email: str,
    reset_url: str,
    application_settings: Settings = settings,
) -> MailDeliveryResult:
    """Send a managed-user password reset link by the configured mail mode."""

    if not application_settings.mail_delivery_configured:
        return _mail_not_configured_result(application_settings)

    return _send_account_email(
        recipient_email=recipient_email,
        subject=PASSWORD_RESET_SUBJECT,
        body=_password_reset_body(reset_url=reset_url, application_settings=application_settings),
        application_settings=application_settings,
        log_context="Password reset email",
    )


def send_welcome_email(
    *,
    recipient_email: str,
    full_name: str,
    username: str,
    application_settings: Settings = settings,
) -> MailDeliveryResult:
    """Send the new-user welcome email by the configured mail mode."""

    safe_recipient_email = recipient_email.strip()
    if not safe_recipient_email:
        return MailDeliveryResult(
            succeeded=False,
            provider=application_settings.mail_mode,
            safe_error="A user email address is required to send a welcome email.",
        )

    app_url = application_settings.app_public_base_url.strip().rstrip("/")
    parsed_app_url = urlparse(app_url)
    if parsed_app_url.scheme not in {"http", "https"} or not parsed_app_url.netloc:
        return MailDeliveryResult(
            succeeded=False,
            provider=application_settings.mail_mode,
            safe_error="APP_PUBLIC_BASE_URL must be an absolute http or https URL to send a welcome email.",
        )

    if not application_settings.mail_delivery_configured:
        return _mail_not_configured_result(application_settings)

    return _send_account_email(
        recipient_email=safe_recipient_email,
        subject=WELCOME_EMAIL_SUBJECT,
        body=build_welcome_email_body(
            full_name=full_name,
            username=username,
            app_url=app_url,
            admin_contact_email=application_settings.admin_contact_email,
        ),
        application_settings=application_settings,
        log_context="Welcome email",
    )


def _send_account_email(
    *,
    recipient_email: str,
    subject: str,
    body: str,
    application_settings: Settings,
    log_context: str,
) -> MailDeliveryResult:
    """Send one account email through the configured provider."""

    if application_settings.mail_mode == "smtp2go":
        return _send_account_email_smtp2go(
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            application_settings=application_settings,
            log_context=log_context,
        )

    return _send_account_email_smtp(
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        application_settings=application_settings,
        log_context=log_context,
    )


def _send_account_email_smtp(
    *,
    recipient_email: str,
    subject: str,
    body: str,
    application_settings: Settings,
    log_context: str,
) -> MailDeliveryResult:
    """Send an app-generated account email by SMTP."""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _sender_address(application_settings)
    message["To"] = recipient_email
    message.set_content(body)

    try:
        if application_settings.mail_smtp_ssl:
            with smtplib.SMTP_SSL(
                application_settings.mail_smtp_host,
                application_settings.mail_smtp_port,
                timeout=application_settings.mail_smtp_timeout_seconds,
            ) as smtp_client:
                _send_message(smtp_client, message, application_settings)
        else:
            with smtplib.SMTP(
                application_settings.mail_smtp_host,
                application_settings.mail_smtp_port,
                timeout=application_settings.mail_smtp_timeout_seconds,
            ) as smtp_client:
                if application_settings.mail_smtp_starttls:
                    smtp_client.starttls()
                _send_message(smtp_client, message, application_settings)
    except (OSError, smtplib.SMTPException) as exc:
        safe_error = _safe_mail_error(exc)
        LOGGER.warning("%s delivery failed: %s", log_context, safe_error)
        return MailDeliveryResult(succeeded=False, provider="smtp", safe_error=safe_error)

    return MailDeliveryResult(succeeded=True, provider="smtp")


def _send_account_email_smtp2go(
    *,
    recipient_email: str,
    subject: str,
    body: str,
    application_settings: Settings,
    log_context: str,
) -> MailDeliveryResult:
    """Send an app-generated account email through SMTP2GO's JSON API."""

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Smtp2go-Api-Key": application_settings.mail_smtp2go_api_key or "",
    }
    payload = {
        "sender": _sender_address(application_settings),
        "to": [recipient_email],
        "subject": subject,
        "text_body": body,
    }
    try:
        with httpx.Client(timeout=application_settings.mail_smtp_timeout_seconds) as http_client:
            response = http_client.post(SMTP2GO_EMAIL_SEND_URL, headers=headers, json=payload)
            response.raise_for_status()
            response_payload = response.json()
    except httpx.HTTPStatusError as exc:
        safe_error = _smtp2go_response_error(exc.response)
        LOGGER.warning("%s delivery failed: %s", log_context, safe_error)
        return MailDeliveryResult(succeeded=False, provider="smtp2go", safe_error=safe_error)
    except (httpx.HTTPError, ValueError) as exc:
        safe_error = _safe_mail_error(exc)
        LOGGER.warning("%s delivery failed: %s", log_context, safe_error)
        return MailDeliveryResult(succeeded=False, provider="smtp2go", safe_error=safe_error)

    response_data = response_payload.get("data", {}) if isinstance(response_payload, dict) else {}
    succeeded_count = _smtp2go_delivery_count(response_data, "succeeded") if isinstance(response_data, dict) else 0
    failed_count = _smtp2go_delivery_count(response_data, "failed") if isinstance(response_data, dict) else 0
    if succeeded_count < 1 or failed_count:
        safe_error = redact_sensitive_text(f"SMTP2GO delivery was not accepted: {response_payload}")[
            :MAX_SAFE_MAIL_ERROR_LENGTH
        ]
        LOGGER.warning("%s delivery failed: %s", log_context, safe_error)
        return MailDeliveryResult(succeeded=False, provider="smtp2go", safe_error=safe_error)

    return MailDeliveryResult(succeeded=True, provider="smtp2go")


def _send_message(smtp_client: smtplib.SMTP, message: EmailMessage, application_settings: Settings) -> None:
    """Authenticate when configured and deliver one message."""

    if application_settings.mail_smtp_username:
        smtp_client.login(application_settings.mail_smtp_username, application_settings.mail_smtp_password or "")
    smtp_client.send_message(message)
