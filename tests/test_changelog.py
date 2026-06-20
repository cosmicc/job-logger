"""Tests for source-controlled version and changelog display."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from job_logger.services.changelog import ChangelogEntry, current_changelog_entry, load_changelog_entries
from job_logger.version import APP_VERSION
from tests.conftest import extract_csrf_token


def test_app_version_starts_at_one_zero_zero() -> None:
    """The first versionized release should be v1.0.0."""

    assert APP_VERSION == "1.0.0"


def test_changelog_file_starts_fresh_at_initial_release() -> None:
    """The source changelog should not expose the old unversioned history."""

    changelog_path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")

    assert "## v1.0.0 - Initial release" in changelog_text
    assert "- Initial release." in changelog_text
    assert "## Unreleased" not in changelog_text
    assert "0.0.1" not in changelog_text


def test_changelog_parser_reads_current_release() -> None:
    """The web page parser should expose the current version entry."""

    entries = load_changelog_entries()
    current_entry = current_changelog_entry(entries)

    assert current_entry == ChangelogEntry(version="v1.0.0", title="Initial release", changes=("Initial release.",))


def test_changelog_route_requires_login(client: TestClient) -> None:
    """Anonymous users should be redirected before seeing release history."""

    response = client.get("/changelog", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_authenticated_changelog_page_renders_current_version(authenticated_client: TestClient) -> None:
    """Managed web users should see the themed release-history page."""

    response = authenticated_client.get("/changelog")

    assert response.status_code == 200
    assert 'class="changelog-shell"' in response.text
    assert "Current version" in response.text
    assert "v1.0.0" in response.text
    assert "Initial release." in response.text
    assert 'href="/changelog"' in authenticated_client.get("/mobile").text


def test_changelog_page_uses_managed_user_theme(authenticated_client: TestClient) -> None:
    """The release-history page should share the per-user theme context."""

    config_response = authenticated_client.get("/config")
    csrf_token = extract_csrf_token(config_response.text)
    save_response = authenticated_client.post(
        "/config",
        headers={"Accept": "application/json", "X-CSRF-Token": csrf_token},
        data={"csrf_token": csrf_token, "theme": "light"},
    )
    assert save_response.status_code == 200

    response = authenticated_client.get("/changelog")

    assert response.status_code == 200
    assert 'class="theme-light"' in response.text


def test_super_admin_can_view_changelog_in_dark_theme(super_admin_client: TestClient) -> None:
    """The config super admin should be able to see the changelog without user settings."""

    response = super_admin_client.get("/changelog")

    assert response.status_code == 200
    assert 'class="theme-dark"' in response.text
    assert "v1.0.0" in response.text
