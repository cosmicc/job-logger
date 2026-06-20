"""Per-user configuration and theme preference helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.enums import ThemeMode
from job_logger.models import UserPreference
from job_logger.security import (
    SUPER_ADMIN_SESSION_KIND,
    WEB_USER_SESSION_KIND,
    current_user_kind_from_session,
    current_username_from_session,
    current_web_user_id_from_session,
)
from job_logger.services.users import username_normalized

DEFAULT_THEME = ThemeMode.DARK
THEME_META_COLORS = {
    ThemeMode.DARK: "#0b1220",
    ThemeMode.LIGHT: "#f6f8fb",
}


class UserPreferenceError(RuntimeError):
    """Raised when user preference input is invalid."""


@dataclass(frozen=True)
class PreferencePrincipal:
    """Stable preference identity for one authenticated login."""

    # key is intentionally independent of display names so settings survive renames.
    key: str

    # label is safe text for the configuration page.
    label: str


def normalize_theme(raw_theme: str | None) -> ThemeMode:
    """Return a supported theme value, defaulting to dark when unset."""

    normalized_theme = (raw_theme or DEFAULT_THEME.value).strip().lower()
    try:
        return ThemeMode(normalized_theme)
    except ValueError as exc:
        raise UserPreferenceError("Theme must be light or dark.") from exc


def preference_principal_from_session(
    session: Mapping[str, object],
    application_settings: Settings = settings,
) -> PreferencePrincipal | None:
    """Return the preference principal for the authenticated session, if any."""

    user_kind = current_user_kind_from_session(session, application_settings)
    username = current_username_from_session(session)
    if user_kind == SUPER_ADMIN_SESSION_KIND and username:
        return PreferencePrincipal(
            key=f"super_admin:{username_normalized(username)}",
            label=f"{username} (super admin)",
        )

    web_user_id = current_web_user_id_from_session(session)
    if user_kind == WEB_USER_SESSION_KIND and web_user_id:
        return PreferencePrincipal(key=f"web_user:{web_user_id}", label=username or "Web user")

    return None


def get_user_preference(database_session: Session, principal_key: str) -> UserPreference | None:
    """Return saved preferences for one authenticated principal."""

    return database_session.scalar(select(UserPreference).where(UserPreference.principal_key == principal_key))


def get_theme_for_principal(database_session: Session, principal_key: str | None) -> ThemeMode:
    """Return a user's saved theme, or the secure default when none exists."""

    if not principal_key:
        return DEFAULT_THEME

    user_preference = get_user_preference(database_session, principal_key)
    return user_preference.theme if user_preference is not None else DEFAULT_THEME


def get_theme_for_session(database_session: Session, session: Mapping[str, object]) -> ThemeMode:
    """Return the saved theme for the current authenticated session."""

    principal = preference_principal_from_session(session)
    return get_theme_for_principal(database_session, principal.key if principal else None)


def save_theme_for_principal(
    database_session: Session,
    *,
    principal_key: str,
    theme: str | None,
) -> UserPreference:
    """Persist one authenticated principal's theme setting."""

    normalized_theme = normalize_theme(theme)
    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        user_preference = UserPreference(principal_key=principal_key, theme=normalized_theme)
        database_session.add(user_preference)
    else:
        user_preference.theme = normalized_theme

    return user_preference
