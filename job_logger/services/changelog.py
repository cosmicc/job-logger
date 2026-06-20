"""Read source-controlled release notes for the authenticated changelog page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from job_logger.version import APP_VERSION

CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


@dataclass(frozen=True)
class ChangelogEntry:
    """One parsed version entry from ``CHANGELOG.md``."""

    version: str
    title: str
    changes: tuple[str, ...]

    @property
    def display_title(self) -> str:
        """Return a useful title when a heading only contains a version."""

        return self.title or "Release notes"


def _fallback_entry() -> ChangelogEntry:
    """Return a conservative entry when the source changelog is unavailable."""

    return ChangelogEntry(version=f"v{APP_VERSION}", title="Initial release", changes=("Initial release.",))


def _parse_heading(raw_heading: str) -> tuple[str, str]:
    """Split a markdown changelog heading into version and title text."""

    version, separator, title = raw_heading.partition(" - ")
    if not separator:
        version, separator, title = raw_heading.partition(": ")
    return version.strip(), title.strip()


def load_changelog_entries(path: Path = CHANGELOG_PATH) -> list[ChangelogEntry]:
    """Load versioned changelog entries from the repository changelog file.

    The parser intentionally supports a small markdown subset: level-two
    headings followed by bullet lines. Rendering escaped plain text keeps the
    release history display predictable and avoids treating changelog content as
    trusted HTML.
    """

    if not path.exists():
        return [_fallback_entry()]

    entries: list[ChangelogEntry] = []
    current_version = ""
    current_title = ""
    current_changes: list[str] = []

    def flush_current_entry() -> None:
        if current_version:
            entries.append(
                ChangelogEntry(
                    version=current_version,
                    title=current_title,
                    changes=tuple(current_changes) or ("No release notes recorded.",),
                )
            )

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped_line = raw_line.strip()
        if stripped_line.startswith("## "):
            flush_current_entry()
            current_version, current_title = _parse_heading(stripped_line[3:].strip())
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

    expected_versions = {APP_VERSION, f"v{APP_VERSION}"}
    for entry in entries:
        if entry.version in expected_versions:
            return entry
    return entries[0] if entries else _fallback_entry()
