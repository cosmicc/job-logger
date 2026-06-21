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
    WEB_USER_SESSION_KIND,
    current_user_kind_from_session,
    current_username_from_session,
    current_web_user_id_from_session,
)

DEFAULT_THEME = ThemeMode.DARK
DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS = False
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


def normalize_submit_from_work_in_progress(raw_enabled: bool | str | None) -> bool:
    """Return whether active-job completion should submit directly to Autotask."""

    if isinstance(raw_enabled, bool):
        return raw_enabled

    normalized_enabled = (raw_enabled or "").strip().casefold()
    if normalized_enabled in {"1", "true", "yes", "on"}:
        return True
    if normalized_enabled in {"", "0", "false", "no", "off"}:
        return False

    raise UserPreferenceError("Submit from Work in Progress must be on or off.")


def preference_principal_from_session(
    session: Mapping[str, object],
    application_settings: Settings = settings,
) -> PreferencePrincipal | None:
    """Return the preference principal for the authenticated session, if any."""

    user_kind = current_user_kind_from_session(session, application_settings)
    username = current_username_from_session(session)
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


def get_submit_from_work_in_progress_for_principal(database_session: Session, principal_key: str | None) -> bool:
    """Return whether one user has enabled direct Work in Progress submission."""

    if not principal_key:
        return DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS

    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        return DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS

    return bool(user_preference.submit_from_work_in_progress)


def get_theme_for_session(database_session: Session, session: Mapping[str, object]) -> ThemeMode:
    """Return the saved theme for the current authenticated session."""

    principal = preference_principal_from_session(session)
    return get_theme_for_principal(database_session, principal.key if principal else None)


def get_submit_from_work_in_progress_for_session(database_session: Session, session: Mapping[str, object]) -> bool:
    """Return the direct-submit setting for the current managed web-user session."""

    principal = preference_principal_from_session(session)
    return get_submit_from_work_in_progress_for_principal(database_session, principal.key if principal else None)


def _new_user_preference(principal_key: str) -> UserPreference:
    """Return a preference row with every secure default set explicitly."""

    return UserPreference(
        principal_key=principal_key,
        theme=DEFAULT_THEME,
        submit_from_work_in_progress=DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS,
    )


def save_preferences_for_principal(
    database_session: Session,
    *,
    principal_key: str,
    theme: str | None = None,
    submit_from_work_in_progress: bool | str | None = None,
) -> UserPreference:
    """Persist supplied configuration values for one authenticated principal."""

    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        user_preference = _new_user_preference(principal_key)
        database_session.add(user_preference)

    if theme is not None:
        user_preference.theme = normalize_theme(theme)

    if submit_from_work_in_progress is not None:
        user_preference.submit_from_work_in_progress = normalize_submit_from_work_in_progress(
            submit_from_work_in_progress
        )

    return user_preference


def save_theme_for_principal(
    database_session: Session,
    *,
    principal_key: str,
    theme: str | None,
) -> UserPreference:
    """Persist one authenticated principal's theme setting."""

    return save_preferences_for_principal(database_session, principal_key=principal_key, theme=theme)
