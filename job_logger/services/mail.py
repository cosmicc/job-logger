"""SMTP mail delivery helpers for Job Logger account workflows."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from job_logger.config import Settings, settings
from job_logger.logging_config import redact_sensitive_text

LOGGER = logging.getLogger(__name__)
MAX_SAFE_MAIL_ERROR_LENGTH = 500


@dataclass(frozen=True)
class MailDeliveryResult:
    """Safe outcome returned after attempting SMTP delivery."""

    succeeded: bool
    provider: str = "smtp"
    safe_error: str | None = None


def _safe_mail_error(exc: Exception) -> str:
    """Return a bounded, redacted SMTP error for audit and diagnostics."""

    error_text = f"{exc.__class__.__name__}: {exc}"
    return redact_sensitive_text(error_text.replace("\r", "\\r").replace("\n", "\\n"))[:MAX_SAFE_MAIL_ERROR_LENGTH]


def _sender_address(application_settings: Settings) -> str:
    """Return the formatted From header for app-generated email."""

    return formataddr((application_settings.mail_from_name, application_settings.mail_from_email))


def send_password_reset_email(
    *,
    recipient_email: str,
    reset_url: str,
    application_settings: Settings = settings,
) -> MailDeliveryResult:
    """Send a managed-user password reset link by SMTP."""

    if not application_settings.password_reset_mail_configured:
        return MailDeliveryResult(succeeded=False, safe_error="SMTP mail is not configured.")

    message = EmailMessage()
    message["Subject"] = "Reset your Job Logger password"
    message["From"] = _sender_address(application_settings)
    message["To"] = recipient_email
    message.set_content(
        "A password reset was requested for your Job Logger account.\n\n"
        f"Reset your password using this link:\n{reset_url}\n\n"
        f"This link is valid for {int(application_settings.password_reset_token_ttl_hours)} hours and can be used only once.\n\n"
        "If you did not request this reset, you can ignore this email."
    )

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
        LOGGER.warning("Password reset email delivery failed: %s", safe_error)
        return MailDeliveryResult(succeeded=False, safe_error=safe_error)

    return MailDeliveryResult(succeeded=True)


def _send_message(smtp_client: smtplib.SMTP, message: EmailMessage, application_settings: Settings) -> None:
    """Authenticate when configured and deliver one message."""

    if application_settings.mail_smtp_username:
        smtp_client.login(application_settings.mail_smtp_username, application_settings.mail_smtp_password or "")
    smtp_client.send_message(message)
