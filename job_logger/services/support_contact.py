"""User-facing support contact message helpers."""

from __future__ import annotations

from fastapi import Request

from job_logger.config import Settings, settings


def application_settings_from_request(request: Request) -> Settings:
    """Return settings attached to an app factory or the process defaults."""

    return getattr(request.app.state, "application_settings", settings)


def disabled_account_message(application_settings: Settings) -> str:
    """Return the safe disabled-account message shown after verified login."""

    if application_settings.admin_contact_email:
        return f"Your account is disabled, please contact {application_settings.admin_contact_email}"
    return "Your account is disabled, please contact your app administrator."


def help_contact_footer(application_settings: Settings) -> str:
    """Return the optional AI Help contact footer."""

    if not application_settings.admin_contact_email:
        return ""
    return f"If you need further help, contact {application_settings.admin_contact_email}"


def append_help_contact_footer(answer_text: str, application_settings: Settings) -> str:
    """Append configured support contact guidance below an AI Help answer."""

    footer = help_contact_footer(application_settings)
    if not footer:
        return answer_text
    return f"{answer_text.rstrip()}\n\n{footer}"
