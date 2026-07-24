"""Per-user configuration and theme preference helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_pilot.config import Settings, settings
from ticket_pilot.enums import HighlightColor, NavigationApp, ThemeMode
from ticket_pilot.models import UserPreference
from ticket_pilot.security import (
    WEB_USER_SESSION_KIND,
    current_user_kind_from_session,
    current_username_from_session,
    current_web_user_id_from_session,
)

DEFAULT_THEME = ThemeMode.DARK
DEFAULT_HIGHLIGHT_COLOR = HighlightColor.TEAL
DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS = False
DEFAULT_NAVIGATION_APP = NavigationApp.NONE
DEFAULT_ALLOW_NAVIGATION_ON_FULL_WEB = False
MAX_NAVIGATION_ADDRESS_LENGTH = 300
THEME_META_COLORS = {
    ThemeMode.DARK: "#0b1220",
    ThemeMode.LIGHT: "#f6f8fb",
    ThemeMode.LIGHT_SAGE: "#f5f7f1",
    ThemeMode.LIGHT_SKY: "#f2f7fb",
    ThemeMode.DARK_MIDNIGHT: "#030508",
    ThemeMode.DARK_GRAPHITE: "#17191d",
    ThemeMode.DARK_FOREST: "#0d1914",
    ThemeMode.DARK_PLUM: "#1a1220",
}


class UserPreferenceError(RuntimeError):
    """Raised when user preference input is invalid."""


@dataclass(frozen=True)
class ThemeOption:
    """User-facing metadata for one supported background profile."""

    value: str
    label: str
    description: str
    family: str
    meta_color: str


@dataclass(frozen=True)
class HighlightOption:
    """User-facing metadata for one contrast-adjusted highlight profile."""

    value: str
    label: str
    dark_preview: str
    light_preview: str


THEME_OPTIONS = (
    ThemeOption(ThemeMode.DARK.value, "Default Dark", "Navy surfaces", "dark", THEME_META_COLORS[ThemeMode.DARK]),
    ThemeOption(
        ThemeMode.DARK_MIDNIGHT.value,
        "Midnight Black",
        "Black and navy surfaces",
        "dark",
        THEME_META_COLORS[ThemeMode.DARK_MIDNIGHT],
    ),
    ThemeOption(
        ThemeMode.DARK_GRAPHITE.value,
        "Graphite Dark",
        "Charcoal surfaces",
        "dark",
        THEME_META_COLORS[ThemeMode.DARK_GRAPHITE],
    ),
    ThemeOption(
        ThemeMode.DARK_FOREST.value,
        "Forest Dark",
        "Evergreen surfaces",
        "dark",
        THEME_META_COLORS[ThemeMode.DARK_FOREST],
    ),
    ThemeOption(
        ThemeMode.DARK_PLUM.value,
        "Plum Dark",
        "Aubergine surfaces",
        "dark",
        THEME_META_COLORS[ThemeMode.DARK_PLUM],
    ),
    ThemeOption(ThemeMode.LIGHT.value, "Default Light", "Cool white surfaces", "light", THEME_META_COLORS[ThemeMode.LIGHT]),
    ThemeOption(
        ThemeMode.LIGHT_SAGE.value,
        "Sage Light",
        "Warm ivory surfaces",
        "light",
        THEME_META_COLORS[ThemeMode.LIGHT_SAGE],
    ),
    ThemeOption(
        ThemeMode.LIGHT_SKY.value,
        "Sky Light",
        "Soft blue surfaces",
        "light",
        THEME_META_COLORS[ThemeMode.LIGHT_SKY],
    ),
)

HIGHLIGHT_OPTIONS = (
    HighlightOption(HighlightColor.TEAL.value, "Teal", "#2dd4bf", "#0f766e"),
    HighlightOption(HighlightColor.SAGE.value, "Sage", "#9fca9f", "#557a5b"),
    HighlightOption(HighlightColor.SKY.value, "Sky Blue", "#76b9e8", "#356f9f"),
    HighlightOption(HighlightColor.BLUE.value, "Blue", "#6699e8", "#3267b1"),
    HighlightOption(HighlightColor.INDIGO.value, "Indigo", "#8b8ff0", "#5558b7"),
    HighlightOption(HighlightColor.AMBER.value, "Amber", "#f2b84b", "#a85f05"),
    HighlightOption(HighlightColor.ORANGE.value, "Orange", "#f59a56", "#b45309"),
    HighlightOption(HighlightColor.MINT.value, "Mint", "#7fc29a", "#367b55"),
    HighlightOption(HighlightColor.LAVENDER.value, "Lavender", "#c49ad7", "#80539a"),
    HighlightOption(HighlightColor.ROSE.value, "Rose", "#e990ad", "#a93f67"),
)

LEGACY_THEME_HIGHLIGHTS = {
    ThemeMode.DARK: HighlightColor.TEAL,
    ThemeMode.LIGHT: HighlightColor.TEAL,
    ThemeMode.LIGHT_SAGE: HighlightColor.SAGE,
    ThemeMode.LIGHT_SKY: HighlightColor.SKY,
    ThemeMode.DARK_MIDNIGHT: HighlightColor.BLUE,
    ThemeMode.DARK_GRAPHITE: HighlightColor.AMBER,
    ThemeMode.DARK_FOREST: HighlightColor.MINT,
    ThemeMode.DARK_PLUM: HighlightColor.LAVENDER,
}


@dataclass(frozen=True)
class PreferencePrincipal:
    """Stable preference identity for one authenticated login."""

    # key is intentionally independent of display names so settings survive renames.
    key: str

    # label is safe text for the configuration page.
    label: str


@dataclass(frozen=True)
class NavigationPreferences:
    """Resolved private navigation settings for one managed user."""

    navigation_app: NavigationApp
    home_address: str | None
    office_address_override: str | None
    effective_office_address: str | None
    allow_navigation_on_full_web: bool


def normalize_theme(raw_theme: str | None) -> ThemeMode:
    """Return a supported background profile, defaulting to dark when unset."""

    normalized_theme = (raw_theme or DEFAULT_THEME.value).strip().lower()
    try:
        return ThemeMode(normalized_theme)
    except ValueError as exc:
        raise UserPreferenceError("Select a supported visual theme.") from exc


def normalize_highlight_color(raw_highlight_color: str | None) -> HighlightColor:
    """Return a supported highlight color, defaulting to teal when unset."""

    normalized_highlight = (raw_highlight_color or DEFAULT_HIGHLIGHT_COLOR.value).strip().lower()
    try:
        return HighlightColor(normalized_highlight)
    except ValueError as exc:
        raise UserPreferenceError("Select a supported highlight color.") from exc


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


def normalize_navigation_app(raw_navigation_app: str | None) -> NavigationApp:
    """Return a supported navigation application key."""

    normalized_app = (raw_navigation_app or DEFAULT_NAVIGATION_APP.value).strip().lower()
    try:
        return NavigationApp(normalized_app)
    except ValueError as exc:
        raise UserPreferenceError("Select a supported navigation application.") from exc


def normalize_allow_navigation_on_full_web(raw_enabled: bool | str | None) -> bool:
    """Return whether navigation may be exposed in full web browsers."""

    if isinstance(raw_enabled, bool):
        return raw_enabled

    normalized_enabled = (raw_enabled or "").strip().casefold()
    if normalized_enabled in {"1", "true", "yes", "on"}:
        return True
    if normalized_enabled in {"", "0", "false", "no", "off"}:
        return False

    raise UserPreferenceError("Allow navigation on full web version must be on or off.")


def normalize_navigation_address(raw_address: str | None, *, field_label: str) -> str | None:
    """Return bounded single-line navigation text without control characters."""

    normalized_address = " ".join((raw_address or "").split())
    if not normalized_address:
        return None
    if len(normalized_address) > MAX_NAVIGATION_ADDRESS_LENGTH:
        raise UserPreferenceError(
            f"{field_label} must be {MAX_NAVIGATION_ADDRESS_LENGTH} characters or fewer."
        )
    return normalized_address


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

    # A single autosave request may update more than one preference group
    # before the new row is flushed. Reuse that pending row so the unique
    # principal key is never inserted twice.
    for pending_object in database_session.new:
        if isinstance(pending_object, UserPreference) and pending_object.principal_key == principal_key:
            return pending_object
    return database_session.scalar(select(UserPreference).where(UserPreference.principal_key == principal_key))


def get_theme_for_principal(database_session: Session, principal_key: str | None) -> ThemeMode:
    """Return a user's saved theme, or the secure default when none exists."""

    if not principal_key:
        return DEFAULT_THEME

    user_preference = get_user_preference(database_session, principal_key)
    return user_preference.theme if user_preference is not None else DEFAULT_THEME


def get_highlight_color_for_principal(
    database_session: Session,
    principal_key: str | None,
) -> HighlightColor:
    """Return a user's saved highlight color, or the default when none exists."""

    if not principal_key:
        return DEFAULT_HIGHLIGHT_COLOR

    user_preference = get_user_preference(database_session, principal_key)
    return user_preference.highlight_color if user_preference is not None else DEFAULT_HIGHLIGHT_COLOR


def get_submit_from_work_in_progress_for_principal(database_session: Session, principal_key: str | None) -> bool:
    """Return whether one user has enabled direct Work in Progress submission."""

    if not principal_key:
        return DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS

    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        return DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS

    return bool(user_preference.submit_from_work_in_progress)


def get_navigation_preferences_for_principal(
    database_session: Session,
    principal_key: str | None,
    application_settings: Settings = settings,
) -> NavigationPreferences:
    """Return one user's navigation settings with the office fallback resolved."""

    user_preference = get_user_preference(database_session, principal_key) if principal_key else None
    navigation_app = user_preference.navigation_app if user_preference else DEFAULT_NAVIGATION_APP
    home_address = user_preference.home_address if user_preference else None
    office_override = user_preference.office_address if user_preference else None
    allow_navigation_on_full_web = (
        bool(user_preference.allow_navigation_on_full_web)
        if user_preference
        else DEFAULT_ALLOW_NAVIGATION_ON_FULL_WEB
    )
    return NavigationPreferences(
        navigation_app=navigation_app,
        home_address=home_address,
        office_address_override=office_override,
        effective_office_address=office_override or application_settings.navigation_office_address or None,
        allow_navigation_on_full_web=allow_navigation_on_full_web,
    )


def get_theme_for_session(database_session: Session, session: Mapping[str, object]) -> ThemeMode:
    """Return the saved theme for the current authenticated session."""

    principal = preference_principal_from_session(session)
    return get_theme_for_principal(database_session, principal.key if principal else None)


def get_highlight_color_for_session(
    database_session: Session,
    session: Mapping[str, object],
) -> HighlightColor:
    """Return the saved highlight color for the current authenticated session."""

    principal = preference_principal_from_session(session)
    return get_highlight_color_for_principal(database_session, principal.key if principal else None)


def get_submit_from_work_in_progress_for_session(database_session: Session, session: Mapping[str, object]) -> bool:
    """Return the direct-submit setting for the current managed web-user session."""

    principal = preference_principal_from_session(session)
    return get_submit_from_work_in_progress_for_principal(database_session, principal.key if principal else None)


def _new_user_preference(principal_key: str) -> UserPreference:
    """Return a preference row with every secure default set explicitly."""

    return UserPreference(
        principal_key=principal_key,
        theme=DEFAULT_THEME,
        highlight_color=DEFAULT_HIGHLIGHT_COLOR,
        submit_from_work_in_progress=DEFAULT_SUBMIT_FROM_WORK_IN_PROGRESS,
        navigation_app=DEFAULT_NAVIGATION_APP,
        allow_navigation_on_full_web=DEFAULT_ALLOW_NAVIGATION_ON_FULL_WEB,
    )


def save_preferences_for_principal(
    database_session: Session,
    *,
    principal_key: str,
    theme: str | None = None,
    highlight_color: str | None = None,
    submit_from_work_in_progress: bool | str | None = None,
) -> UserPreference:
    """Persist supplied configuration values for one authenticated principal."""

    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        user_preference = _new_user_preference(principal_key)
        database_session.add(user_preference)

    if theme is not None:
        user_preference.theme = normalize_theme(theme)

    if highlight_color is not None:
        user_preference.highlight_color = normalize_highlight_color(highlight_color)

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


def save_navigation_preferences_for_principal(
    database_session: Session,
    *,
    principal_key: str,
    navigation_app: str | None,
    home_address: str | None,
    office_address: str | None,
    allow_navigation_on_full_web: bool | str | None,
) -> UserPreference:
    """Validate and persist private navigation settings for one managed user."""

    normalized_app = normalize_navigation_app(navigation_app)
    normalized_home = normalize_navigation_address(home_address, field_label="Home address")
    normalized_office = normalize_navigation_address(office_address, field_label="Office address")
    normalized_allow_full_web = normalize_allow_navigation_on_full_web(allow_navigation_on_full_web)
    if normalized_app != NavigationApp.NONE and normalized_home is None:
        raise UserPreferenceError("Home address is required when navigation is enabled.")
    if normalized_app == NavigationApp.NONE:
        normalized_allow_full_web = False

    user_preference = get_user_preference(database_session, principal_key)
    if user_preference is None:
        user_preference = _new_user_preference(principal_key)
        database_session.add(user_preference)

    user_preference.navigation_app = normalized_app
    user_preference.home_address = normalized_home
    user_preference.office_address = normalized_office
    user_preference.allow_navigation_on_full_web = normalized_allow_full_web
    return user_preference
