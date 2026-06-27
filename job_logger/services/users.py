"""Managed web-user validation, password hashing, and persistence helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from job_logger.config import Settings, settings
from job_logger.models import Job, WebUser, utc_now
from job_logger.services.session_control import invalidate_web_user_sessions

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024
MAX_USERNAME_LENGTH = 120
MAX_FULL_NAME_LENGTH = 160
MAX_EMAIL_LENGTH = 254
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]+$")
USERNAME_AUTOGENERATE_STRIP_PATTERN = re.compile(r"[^A-Za-z0-9]")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_LOWERCASE_PATTERN = re.compile(r"[a-z]")
PASSWORD_UPPERCASE_PATTERN = re.compile(r"[A-Z]")
PASSWORD_DIGIT_PATTERN = re.compile(r"\d")
PASSWORD_SYMBOL_PATTERN = re.compile(r"[^A-Za-z0-9]")


class WebUserError(RuntimeError):
    """Raised when a managed web-user operation is invalid."""


@dataclass(frozen=True)
class WebUserCreateResult:
    """Result returned after creating a managed web user."""

    # user is the created managed account.
    user: WebUser

    # claimed_unowned_job_count records legacy jobs assigned to the first user.
    claimed_unowned_job_count: int


@dataclass(frozen=True)
class WebUserDeleteResult:
    """Result returned after a delete request."""

    # deleted is retained for callers that distinguish legacy hard deletes.
    # Current delete requests disable users so future login attempts can show a
    # disabled-account message instead of looking like unknown usernames.
    deleted: bool

    # disabled is true when the account row was preserved and blocked.
    disabled: bool

    # related_job_count records how much work history remains linked.
    related_job_count: int


@dataclass(frozen=True)
class WebUserAuthenticationResult:
    """Result returned after checking managed-user login credentials."""

    # user is populated only when credentials belong to an enabled account.
    user: WebUser | None

    # disabled_user is populated only after the submitted password verifies for
    # a disabled account. Wrong passwords still look like generic failures so
    # login does not reveal account existence.
    disabled_user: WebUser | None = None


def username_normalized(username: str) -> str:
    """Return the case-insensitive key used for login lookup and uniqueness."""

    return username.strip().casefold()


def normalize_full_name(full_name: str | None) -> str:
    """Return a required bounded display name."""

    normalized_full_name = (full_name or "").strip()
    if not normalized_full_name:
        raise WebUserError("Full name is required.")
    if len(normalized_full_name) > MAX_FULL_NAME_LENGTH:
        raise WebUserError(f"Full name must be {MAX_FULL_NAME_LENGTH} characters or fewer.")
    return normalized_full_name


def normalize_username(username: str | None, application_settings: Settings = settings) -> str:
    """Return a required bounded username that cannot collide with super admin."""

    normalized_username = (username or "").strip()
    if not normalized_username:
        raise WebUserError("Username is required.")
    if len(normalized_username) > MAX_USERNAME_LENGTH:
        raise WebUserError(f"Username must be {MAX_USERNAME_LENGTH} characters or fewer.")
    if not USERNAME_PATTERN.fullmatch(normalized_username):
        raise WebUserError("Username may contain only letters, numbers, dots, underscores, hyphens, and @.")
    if username_normalized(normalized_username) == username_normalized(application_settings.app_username):
        raise WebUserError("That username is reserved for the config super admin.")
    return normalized_username


def suggested_username_from_full_name(full_name: str | None) -> str:
    """Return the default username suggestion for a technician's full name."""

    name_parts = [
        USERNAME_AUTOGENERATE_STRIP_PATTERN.sub("", name_part)
        for name_part in (full_name or "").strip().split()
    ]
    name_parts = [name_part for name_part in name_parts if name_part]
    if len(name_parts) < 2:
        return ""

    first_name = name_parts[0]
    last_name = name_parts[-1]
    if not first_name or not last_name:
        return ""

    return f"{first_name[0]}{last_name}".lower()[:MAX_USERNAME_LENGTH]


def normalize_autotask_resource_id(raw_resource_id: int | str | None) -> int:
    """Return a required positive Autotask resource ID."""

    if raw_resource_id is None or (isinstance(raw_resource_id, str) and not raw_resource_id.strip()):
        raise WebUserError("Autotask resource ID is required.")
    try:
        resource_id = int(raw_resource_id)
    except (TypeError, ValueError) as exc:
        raise WebUserError("Autotask resource ID must be a positive number.") from exc
    if resource_id <= 0:
        raise WebUserError("Autotask resource ID must be a positive number.")
    return resource_id


def normalize_optional_autotask_role_id(raw_role_id: int | str | None) -> int | None:
    """Return an optional positive Autotask service-desk role ID."""

    if raw_role_id is None or (isinstance(raw_role_id, str) and not raw_role_id.strip()):
        return None
    try:
        role_id = int(raw_role_id)
    except (TypeError, ValueError) as exc:
        raise WebUserError("Default service desk role must be a positive number.") from exc
    if role_id <= 0:
        raise WebUserError("Default service desk role must be a positive number.")
    return role_id


def normalize_optional_email(email: str | None) -> str | None:
    """Return a bounded optional email captured from Autotask Resource lookup."""

    normalized_email = (email or "").strip()
    if not normalized_email:
        return None
    if len(normalized_email) > MAX_EMAIL_LENGTH:
        raise WebUserError(f"Email must be {MAX_EMAIL_LENGTH} characters or fewer.")
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        raise WebUserError("Email must be a valid address.")
    return normalized_email


def _normalize_new_password(password: str | None) -> str:
    """Return a required bounded password for storage."""

    normalized_password = password or ""
    if not normalized_password:
        raise WebUserError("Password is required.")
    if len(normalized_password) < MIN_PASSWORD_LENGTH:
        raise WebUserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(normalized_password) > MAX_PASSWORD_LENGTH:
        raise WebUserError(f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer.")
    if not PASSWORD_LOWERCASE_PATTERN.search(normalized_password):
        raise WebUserError("Password must include at least one lowercase letter.")
    if not PASSWORD_UPPERCASE_PATTERN.search(normalized_password):
        raise WebUserError("Password must include at least one uppercase letter.")
    if not PASSWORD_DIGIT_PATTERN.search(normalized_password):
        raise WebUserError("Password must include at least one number.")
    if not PASSWORD_SYMBOL_PATTERN.search(normalized_password):
        raise WebUserError("Password must include at least one symbol.")
    return normalized_password


def _base64_no_padding(raw_bytes: bytes) -> str:
    """Return URL-safe base64 without padding for compact verifier storage."""

    return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")


def _decode_base64_no_padding(encoded_value: str) -> bytes:
    """Decode URL-safe base64 that may omit padding."""

    padding = "=" * (-len(encoded_value) % 4)
    return base64.urlsafe_b64decode(f"{encoded_value}{padding}".encode("ascii"))


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 verifier for a managed web-user password."""

    normalized_password = _normalize_new_password(password)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        normalized_password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
        dklen=PASSWORD_HASH_BYTES,
    )
    return (
        f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}"
        f"${_base64_no_padding(salt)}${_base64_no_padding(derived_key)}"
    )


def verify_web_user_password(password: str, password_hash: str) -> bool:
    """Validate a submitted password against a stored PBKDF2 verifier."""

    try:
        algorithm, raw_iterations, encoded_salt, encoded_hash = password_hash.split("$", 3)
        iterations = int(raw_iterations)
        salt = _decode_base64_no_padding(encoded_salt)
        expected_hash = _decode_base64_no_padding(encoded_hash)
    except (ValueError, TypeError):
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM or iterations <= 0 or not salt or not expected_hash:
        return False

    submitted_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected_hash),
    )
    return hmac.compare_digest(expected_hash, submitted_hash)


def list_web_users(database_session: Session) -> list[WebUser]:
    """Return managed web users ordered for the admin list."""

    return list(database_session.execute(select(WebUser).order_by(WebUser.full_name, WebUser.username)).scalars())


def get_web_user_by_id(database_session: Session, user_id: str | None) -> WebUser | None:
    """Return one managed web user by stable ID."""

    if not user_id:
        return None
    return database_session.get(WebUser, user_id)


def get_web_user_by_id_or_raise(database_session: Session, user_id: str | None) -> WebUser:
    """Return one managed web user or raise a safe validation error."""

    user = get_web_user_by_id(database_session, user_id)
    if user is None:
        raise WebUserError("User was not found.")
    return user


def get_enabled_web_user_by_id_or_raise(database_session: Session, user_id: str | None) -> WebUser:
    """Return an enabled managed web user or raise a safe validation error."""

    user = get_web_user_by_id_or_raise(database_session, user_id)
    if user.disabled:
        raise WebUserError("This user account is disabled.")
    return user


def find_web_user_by_username(database_session: Session, username: str) -> WebUser | None:
    """Return a managed web user by case-insensitive username."""

    normalized_username = username_normalized(username)
    if not normalized_username:
        return None
    return database_session.scalar(select(WebUser).where(WebUser.username_normalized == normalized_username))


def authenticate_web_user(database_session: Session, username: str, password: str) -> WebUser | None:
    """Return an enabled web user when the submitted credentials are valid."""

    return authenticate_web_user_with_status(database_session, username, password).user


def authenticate_web_user_with_status(
    database_session: Session,
    username: str,
    password: str,
) -> WebUserAuthenticationResult:
    """Return enabled users or a verified disabled-user state for login UI."""

    user = find_web_user_by_username(database_session, username)
    if user is None:
        return WebUserAuthenticationResult(user=None)
    if not verify_web_user_password(password, user.password_hash):
        return WebUserAuthenticationResult(user=None)
    if user.disabled:
        return WebUserAuthenticationResult(user=None, disabled_user=user)
    return WebUserAuthenticationResult(user=user)


def mark_web_user_login_succeeded(user: WebUser) -> WebUser:
    """Stamp safe account metadata after a successful managed-user login."""

    user.last_login_at_utc = utc_now()
    return user


def _ensure_username_is_available(
    database_session: Session,
    username: str,
    *,
    existing_user_id: str | None = None,
) -> None:
    """Reject duplicate managed usernames."""

    existing_user = database_session.scalar(
        select(WebUser).where(WebUser.username_normalized == username_normalized(username))
    )
    if existing_user is not None and existing_user.id != existing_user_id:
        raise WebUserError("That username is already in use.")


def _managed_user_count(database_session: Session) -> int:
    """Return the number of existing managed web users."""

    return int(database_session.scalar(select(func.count(WebUser.id))) or 0)


def _job_count_for_user(database_session: Session, user: WebUser) -> int:
    """Return how many jobs reference a managed web user."""

    return int(database_session.scalar(select(func.count(Job.id)).where(Job.web_user_id == user.id)) or 0)


def create_web_user(
    database_session: Session,
    *,
    full_name: str | None,
    username: str | None,
    password: str | None,
    autotask_resource_id: int | str | None,
    autotask_default_service_desk_role_id: int | str | None = None,
    email: str | None = None,
    disabled: bool = False,
    is_admin: bool = False,
) -> WebUserCreateResult:
    """Create a managed user and assign legacy jobs when this is the first one."""

    was_first_managed_user = _managed_user_count(database_session) == 0
    normalized_full_name = normalize_full_name(full_name)
    normalized_username = normalize_username(username)
    _ensure_username_is_available(database_session, normalized_username)
    user = WebUser(
        full_name=normalized_full_name,
        username=normalized_username,
        username_normalized=username_normalized(normalized_username),
        password_hash=hash_password(password or ""),
        autotask_resource_id=normalize_autotask_resource_id(autotask_resource_id),
        autotask_default_service_desk_role_id=normalize_optional_autotask_role_id(autotask_default_service_desk_role_id),
        email=normalize_optional_email(email),
        disabled=disabled,
        is_admin=is_admin,
    )
    database_session.add(user)
    database_session.flush()

    claimed_unowned_job_count = 0
    if was_first_managed_user:
        claimed_unowned_job_count = int(
            database_session.execute(
                update(Job).where(Job.web_user_id.is_(None)).values(web_user_id=user.id)
            ).rowcount
            or 0
        )

    return WebUserCreateResult(user=user, claimed_unowned_job_count=claimed_unowned_job_count)


def update_web_user(
    database_session: Session,
    user: WebUser,
    *,
    full_name: str | None,
    username: str | None,
    password: str | None,
    autotask_resource_id: int | str | None,
    autotask_default_service_desk_role_id: int | str | None,
    email: str | None,
    disabled: bool,
    is_admin: bool,
) -> WebUser:
    """Update editable managed-user fields, including optional password reset."""

    was_disabled = user.disabled
    normalized_username = normalize_username(username)
    _ensure_username_is_available(database_session, normalized_username, existing_user_id=user.id)
    user.full_name = normalize_full_name(full_name)
    user.username = normalized_username
    user.username_normalized = username_normalized(normalized_username)
    if password:
        user.password_hash = hash_password(password)
    user.autotask_resource_id = normalize_autotask_resource_id(autotask_resource_id)
    user.autotask_default_service_desk_role_id = normalize_optional_autotask_role_id(autotask_default_service_desk_role_id)
    user.email = normalize_optional_email(email)
    user.disabled = disabled
    user.is_admin = is_admin
    if disabled and not was_disabled:
        invalidate_web_user_sessions(user)
    return user


def change_web_user_password(
    database_session: Session,
    user: WebUser,
    *,
    new_password: str | None,
    confirm_password: str | None,
) -> WebUser:
    """Change a managed web user's password after confirming both entries match."""

    if (new_password or "") != (confirm_password or ""):
        raise WebUserError("Password entries must match.")
    user.password_hash = hash_password(new_password or "")
    database_session.add(user)
    return user


def delete_or_disable_web_user(database_session: Session, user: WebUser) -> WebUserDeleteResult:
    """Disable a managed user and invalidate any existing signed sessions."""

    related_job_count = _job_count_for_user(database_session, user)
    user.disabled = True
    invalidate_web_user_sessions(user)
    return WebUserDeleteResult(deleted=False, disabled=True, related_job_count=related_job_count)
