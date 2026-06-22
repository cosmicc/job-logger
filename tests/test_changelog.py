"""Tests for source-controlled version and changelog display."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from job_logger.services.changelog import ChangelogEntry, current_changelog_entry, load_changelog_entries
from job_logger.version import APP_VERSION
from tests.conftest import extract_csrf_token


def test_app_version_matches_current_release() -> None:
    """The source-controlled version should match the current release."""

    assert APP_VERSION == "1.1.1"


def test_detailed_and_web_changelogs_stay_versioned() -> None:
    """Both changelog sources should stay versioned without old history."""

    repository_root = Path(__file__).resolve().parents[1]
    changelog_text = (repository_root / "CHANGELOG.md").read_text(encoding="utf-8")
    web_changelog_text = (repository_root / "WEB_CHANGELOG.md").read_text(encoding="utf-8")

    assert "## v1.1.1 - Review cleanup, Autotask fixes, and Docker startup" in changelog_text
    assert "## v1.1.0 - Direct submission, backups, and passkeys" in changelog_text
    assert "## v1.0.2 - Autotask workflow and desktop layout updates" in changelog_text
    assert "## v1.0.1 - Mobile shell navigation and close behavior" in changelog_text
    assert "## v1.0.0 - Initial release" in changelog_text
    assert "- Initial release." in changelog_text
    assert "## v1.1.1 - Review action cleanup and Autotask submission fixes" in web_changelog_text
    assert "## v1.1.0 - Direct submission and passkeys" in web_changelog_text
    assert "## v1.0.2 - Autotask workflow and desktop layout updates" in web_changelog_text
    assert "## v1.0.1 - Mobile shell navigation and close behavior" in web_changelog_text
    assert "## v1.0.0 - Initial release" in web_changelog_text
    assert "- Initial release." in web_changelog_text
    assert "## Unreleased" not in changelog_text
    assert "## Unreleased" not in web_changelog_text
    assert "0.0.1" not in changelog_text
    assert "0.0.1" not in web_changelog_text
    assert "WEB_CHANGELOG.md" in changelog_text
    assert "Diagnostics" not in web_changelog_text
    assert "debug page" not in web_changelog_text
    assert "super admin" not in web_changelog_text.lower()


def test_web_changelog_is_available_to_runtime_artifacts() -> None:
    """Docker and wheel builds should include the concise web changelog source."""

    repository_root = Path(__file__).resolve().parents[1]
    dockerfile_text = (repository_root / "Dockerfile").read_text(encoding="utf-8")
    pyproject = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))
    wheel_force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert "WEB_CHANGELOG.md" in dockerfile_text
    assert wheel_force_include["WEB_CHANGELOG.md"] == "job_logger/WEB_CHANGELOG.md"


def test_changelog_parser_reads_current_release() -> None:
    """The web page parser should expose the current version entry."""

    entries = load_changelog_entries()
    current_entry = current_changelog_entry(entries)

    assert current_entry == ChangelogEntry(
        version="v1.1.1",
        title="Review action cleanup and Autotask submission fixes",
        changes=(
            "Review detail now uses compact action rows like Work in Progress.",
            "Record and AI Cleanup now share a row on review detail with shorter labels and icons.",
            "Full browser Work in Progress and Review buttons now use cleaner paired rows.",
            "Autotask submission now handles tickets that provide an assigned resource but omit the assigned role.",
            "Autotask submission now handles tickets where the submitting user is assigned as a secondary resource.",
        ),
    )


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
    assert "v1.1.1" in response.text
    assert "v1.1.0" in response.text
    assert "v1.0.2" in response.text
    assert "v1.0.1" in response.text
    assert "v1.0.0" in response.text
    assert "Review action cleanup" in response.text
    assert "Review detail now uses compact action rows like Work in Progress." in response.text
    assert "Record and AI Cleanup now share a row on review detail with shorter labels and icons." in response.text
    assert "Full browser Work in Progress and Review buttons now use cleaner paired rows." in response.text
    assert "Autotask submission now handles tickets that provide an assigned resource but omit the assigned role." in response.text
    assert "Autotask submission now handles tickets where the submitting user is assigned as a secondary resource." in response.text
    assert "Direct submission and passkeys" in response.text
    assert "Added a Config option to submit time entries directly from Work in Progress." in response.text
    assert "Review is still available afterward for submitted-entry edits and Autotask deletion." in response.text
    assert "Added passkey sign-in for managed users, with password login still available." in response.text
    assert "App sessions can now require users to sign in again after the configured timeout." in response.text
    assert "Disabled users are signed out and see an account-disabled message when they try to log in." in response.text
    assert "The Home passkey setup card now appears only once after login" in response.text
    assert "Ticket source can now mark alert-created tickets as Remote" in response.text
    assert "Review detail now shows the active Work in Progress rounded stop time" in response.text
    assert "Review open-ticket choices now match Work in Progress ticket card details and colors." in response.text
    assert "The mobile top bar now uses a logout icon instead of the app-close X." in response.text
    assert "Mobile Work in Progress actions now use compact button rows with shorter labels and icons." in response.text
    assert "Rounded start and stop `-15` and `+15` buttons no longer show the full-page status overlay." in response.text
    assert "Mobile Summary notes boxes now start taller while still allowing manual resize." in response.text
    assert "automatic database backups" not in response.text
    assert "debug page" not in response.text
    assert "Diagnostics can now log out all managed web users" not in response.text
    assert "Diagnostics now highlights super admin successful logins" not in response.text
    assert "super admin" not in response.text.lower()
    assert "Autotask workflow and desktop layout updates" in response.text
    assert "Edit Entry can update submitted time entries that were already marked Complete." in response.text
    assert "Starting work on a New ticket now moves it to In progress." in response.text
    assert "Work in Progress now shows an editable ticket status field." in response.text
    assert "Open-ticket choices now show Remote or On-Site with matching colors." in response.text
    assert "The Config password card now shows password requirements without a separate current-settings card." in response.text
    assert "The full browser Home and Work in Progress layouts are wider and easier to scan." in response.text
    assert "Mobile shell navigation and close behavior" in response.text
    assert "Mobile users now have version, Home, Review, Config, and close icons in the top bar." in response.text
    assert "The mobile close button exits the app screen without logging out." in response.text
    assert "The changelog page now shows short release notes for each version." in response.text
    assert "The mobile home page now starts directly with the work-entry card." in response.text
    assert response.text.index("Review action cleanup") < response.text.index("Direct submission and passkeys")
    assert response.text.index("Direct submission and passkeys") < response.text.index("Autotask workflow and desktop layout updates")
    assert response.text.index("Autotask workflow and desktop layout updates") < response.text.index("Mobile shell navigation and close behavior")
    assert response.text.index("Mobile shell navigation and close behavior") < response.text.index("Initial release")
    assert '<h2 id="current-version-heading">Review action cleanup and Autotask submission fixes</h2>' in response.text
    assert '<span class="release-version">v1.1.1</span>' in response.text
    assert '<span class="release-version">v1.1.0</span>' in response.text
    assert '<span class="release-version">v1.0.2</span>' in response.text
    assert '<span class="release-version">v1.0.1</span>' in response.text
    assert '<span class="release-version">v1.0.0</span>' in response.text
    assert 'class="changelog-entry is-current"' not in response.text
    assert 'class="secondary-link-button" href="/review"' not in response.text
    assert "managed-web-user-only Config gear icon" not in response.text
    assert "direct app-shell close behavior first" not in response.text
    for entry in load_changelog_entries():
        assert entry.version in response.text
        for change in entry.changes:
            assert change.replace("'", "&#39;") in response.text
    assert 'href="/changelog"' in authenticated_client.get("/home").text


def test_changelog_title_uses_bold_page_heading_style() -> None:
    """The changelog page title should keep an explicit bold heading style."""

    stylesheet = (Path(__file__).resolve().parents[1] / "job_logger" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".changelog-page-header h1" in stylesheet
    assert ".changelog-current-panel h2,\n.changelog-entry-panel h2" in stylesheet
    assert "font-weight: 950;" in stylesheet


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
    assert "v1.1.1" in response.text
