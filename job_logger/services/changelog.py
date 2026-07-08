"""Read concise web release notes for the authenticated changelog page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from job_logger.version import APP_VERSION

WEB_CHANGELOG_FILE_NAMES = ("WEB_CHANGELOG.md", "web_changelog.md")
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WEB_CHANGELOG_PATH = REPOSITORY_ROOT / "WEB_CHANGELOG.md"
RELEASE_DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{4}")


@dataclass(frozen=True)
class ChangelogEntry:
    """One parsed version entry from ``WEB_CHANGELOG.md``."""

    version: str
    release_date: str
    title: str
    changes: tuple[str, ...]

    @property
    def display_title(self) -> str:
        """Return a useful title when a heading only contains a version."""

        return self.title or "Release notes"


def _fallback_entry() -> ChangelogEntry:
    """Return a conservative entry when the source changelog is unavailable."""

    return ChangelogEntry(version=APP_VERSION, release_date="", title="Initial release", changes=("Initial release.",))


def _normalize_version(raw_version: str) -> str:
    """Return a comparable semantic version without display-only markers."""

    version = raw_version.strip()
    if version.startswith("[") and version.endswith("]"):
        version = version[1:-1].strip()
    if version.lower().startswith("v"):
        version = version[1:].strip()
    return version


def _parse_heading(raw_heading: str) -> tuple[str, str, str]:
    """Split a markdown changelog heading into version, release date, and title."""

    version_text = raw_heading
    trailing_text = ""
    for separator in (" - ", ": "):
        version_text, found_separator, trailing_text = raw_heading.partition(separator)
        if found_separator:
            break

    version = _normalize_version(version_text)
    release_date = ""
    title = trailing_text.strip()
    if " - " in trailing_text:
        possible_date, _, possible_title = trailing_text.partition(" - ")
        if RELEASE_DATE_PATTERN.fullmatch(possible_date.strip()):
            release_date = possible_date.strip()
            title = possible_title.strip()
    elif RELEASE_DATE_PATTERN.fullmatch(title):
        release_date = title
        title = ""
    return version, release_date, title


def _default_changelog_paths() -> tuple[Path, ...]:
    """Return source locations used across local, Docker, and wheel installs."""

    candidates: list[Path] = []
    for base_path in (REPOSITORY_ROOT, Path.cwd(), PACKAGE_ROOT):
        for file_name in WEB_CHANGELOG_FILE_NAMES:
            candidate_path = base_path / file_name
            if candidate_path not in candidates:
                candidates.append(candidate_path)
    return tuple(candidates)


def _resolve_changelog_path(path: Path | None) -> Path | None:
    """Find the changelog source without silently inventing release content."""

    if path is not None:
        return path if path.exists() else None

    for candidate_path in _default_changelog_paths():
        if candidate_path.exists():
            return candidate_path
    return None


def load_changelog_entries(path: Path | None = None) -> list[ChangelogEntry]:
    """Load versioned web changelog entries from the concise web changelog file.

    The parser intentionally supports a small markdown subset: level-two
    version headings, optional level-three section headings, and short bullet
    lines. Rendering escaped plain text keeps the release history display
    predictable and avoids treating changelog content as trusted HTML.
    """

    resolved_path = _resolve_changelog_path(path)
    if resolved_path is None:
        return [_fallback_entry()]

    entries: list[ChangelogEntry] = []
    current_version = ""
    current_release_date = ""
    current_title = ""
    current_changes: list[str] = []

    def flush_current_entry() -> None:
        if current_version:
            entries.append(
                ChangelogEntry(
                    version=current_version,
                    release_date=current_release_date,
                    title=current_title,
                    changes=tuple(current_changes) or ("No release notes recorded.",),
                )
            )

    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if stripped_line.startswith("## "):
            flush_current_entry()
            current_version, current_release_date, current_title = _parse_heading(stripped_line[3:].strip())
            current_changes = []
            continue

        if current_version and stripped_line.startswith("- "):
            current_changes.append(stripped_line[2:].strip())
            continue

        if current_version and current_changes and raw_line.startswith(("  ", "\t")) and stripped_line:
            current_changes[-1] = f"{current_changes[-1]} {stripped_line}"

    flush_current_entry()
    return entries or [_fallback_entry()]


def current_changelog_entry(entries: list[ChangelogEntry]) -> ChangelogEntry:
    """Return the entry matching ``APP_VERSION``, falling back to the newest."""

    expected_version = _normalize_version(APP_VERSION)
    for entry in entries:
        if _normalize_version(entry.version) == expected_version:
            return entry
    return entries[0] if entries else _fallback_entry()
