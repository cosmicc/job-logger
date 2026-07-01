"""Tests for source-controlled version and changelog display."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from job_logger.services.changelog import (
    ChangelogEntry,
    current_changelog_entry,
    load_changelog_entries,
)
from job_logger.version import APP_VERSION
from tests.conftest import extract_csrf_token

CURRENT_DETAILED_HEADING = (
    "## v1.2.0 - Ticket note mode, ticket history, Work in Progress layout, navigation, and web-edge errors"
)
CURRENT_WEB_TITLE = "Ticket note mode, ticket history, Work in Progress layout, navigation, and web-edge polish"
CURRENT_WEB_HEADING = f"## v1.2.0 - {CURRENT_WEB_TITLE}"


def test_app_version_matches_current_release() -> None:
    """The source-controlled version should match the current release."""

    assert APP_VERSION == "1.2.0"


def test_detailed_and_web_changelogs_stay_versioned() -> None:
    """Both changelog sources should stay versioned without old history."""

    repository_root = Path(__file__).resolve().parents[1]
    changelog_text = (repository_root / "CHANGELOG.md").read_text(encoding="utf-8")
    web_changelog_text = (repository_root / "WEB_CHANGELOG.md").read_text(encoding="utf-8")

    assert CURRENT_DETAILED_HEADING in changelog_text
    assert "## v1.1.6 - Cloudflare block controls, Review, Home, and header polish" in changelog_text
    assert "## v1.1.5 - AI cleanup revert, remote transcription, and login diagnostics" in changelog_text
    assert "## v1.1.4 - Login protection, Work in Progress controls, diagnostics, and deployment safety" in changelog_text
    assert "## v1.1.3 - Review visibility and Work in Progress refinements" in changelog_text
    assert "## v1.1.2 - User management, ticket status, and Device sign-in updates" in changelog_text
    assert "## v1.1.1 - Review cleanup, Autotask roles, Docker startup, and diagnostics" in changelog_text
    assert "## v1.1.0 - Direct submission, backups, and passkeys" in changelog_text
    assert "## v1.0.2 - Autotask workflow and desktop layout updates" in changelog_text
    assert "## v1.0.1 - Mobile shell navigation and close behavior" in changelog_text
    assert "## v1.0.0 - Initial release" in changelog_text
    assert "- Initial release." in changelog_text
    assert CURRENT_WEB_HEADING in web_changelog_text
    assert "## v1.1.6 - Review, Home, and header polish" in web_changelog_text
    assert "## v1.1.5 - AI cleanup, speech-to-text, and sign-in updates" in web_changelog_text
    assert "## v1.1.4 - Login protection, Work in Progress controls, and deployment safety" in web_changelog_text
    assert "## v1.1.3 - Review visibility and Work in Progress refinements" in web_changelog_text
    assert "## v1.1.2 - User management, ticket status, and Device sign-in updates" in web_changelog_text
    assert "## v1.1.1 - Review action cleanup and Autotask role fixes" in web_changelog_text
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
        version="v1.2.0",
        title=CURRENT_WEB_TITLE,
        changes=(
            "Date choosers now use Today, Cancel, and Set controls inside the app.",
            "Start and end time fields now open a 15-minute time dropdown.",
            "Switching a Time entry to a Ticket note now removes the Remote. or On-Site. prefix from the note description.",
            "Switching back to Time entry restores the Remote. or On-Site. prefix that matches the selected work type.",
            "Ticket note mode now shows Note Date and hides start/end time fields until switching back to Time entry.",
            (
                "Ticket history now filters system-generated notes, including Workflow Rule title variants, "
                "and shows No Notes or No past entries "
                "when the selected ticket has no usable history."
            ),
            "Past time entry cards now show compact hours beside the resource name, such as 1.5hrs.",
            "Full-browser navigation is now centered and uses the app's home-screen icon in the header.",
            (
                "The work-entry navigation button now says Work, uses a work-entry icon, "
                "and the mobile top-bar buttons use the same blue style as the full web nav."
            ),
            (
                "Work in Progress and Review detail now show the ticket title with the state pill beside it, "
                "center key field labels, and use matching action button sizes."
            ),
            (
                "Work in Progress active cards show the Work in Progress label again, "
                "and full-browser summary notes line up with the job date cards."
            ),
            (
                "The full-browser Work page Job date card stays full-width, "
                "while the date selector inside it is compact."
            ),
            (
                "The full-browser Work page note-title and summary boxes now start flush "
                "with the Job date or Note Date card."
            ),
            "Empty No Notes and No past entries buttons now stay fully disabled with no hover or click behavior.",
            "The app-health degraded icon now appears for every signed-in user without opening another page.",
            "Web service and missing-page errors now match Job Logger's look and offer Back to Login or Back to Work.",
            "Work entries can now be Time entries or customer-visible Ticket notes.",
            "Ticket note mode uses a required note title and note description instead of time and Remote/On-Site fields.",
            (
                "Append to resolution is available for both entry types, "
                "and submitted Ticket notes can be updated or deleted from Review."
            ),
            "Ticket notes now open from the selected ticket in a closeable newest-first overlay.",
            (
                "A Past time entries button now opens ticket time entries with clear technician names, "
                "large time details, and summary-of-work details."
            ),
            "Work entry save, recording, and AI Cleanup messages now share one status line.",
            (
                "Job date controls now center the date with Today, Yesterday, or Tomorrow "
                "inside the selector when applicable."
            ),
            "Ticket note fields are tighter, with Append to resolution below the note description.",
            "Full-browser navigation now uses raised blue icon buttons with visible labels.",
            "Buttons now have clear hover and pressed states, including red destructive actions staying red on hover.",
            (
                "Work in Progress and Review now have clean time controls, larger Remote/On-Site pills, "
                "and rounded total time shown."
            ),
            "Full-browser Review now keeps Entry type beside Job date so start and end times share a row.",
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
    assert "v1.2.0" in response.text
    assert "v1.1.6" in response.text
    assert "v1.1.5" in response.text
    assert "v1.1.4" in response.text
    assert "v1.1.3" in response.text
    assert "v1.1.2" in response.text
    assert "v1.1.1" in response.text
    assert "v1.1.0" in response.text
    assert "v1.0.2" in response.text
    assert "v1.0.1" in response.text
    assert "v1.0.0" in response.text
    assert CURRENT_WEB_TITLE in response.text
    assert "Date choosers now use Today, Cancel, and Set controls inside the app." in response.text
    assert "Start and end time fields now open a 15-minute time dropdown." in response.text
    assert "Switching a Time entry to a Ticket note now removes the Remote. or On-Site. prefix from the note description." in response.text
    assert "Switching back to Time entry restores the Remote. or On-Site. prefix that matches the selected work type." in response.text
    assert "Ticket note mode now shows Note Date and hides start/end time fields until switching back to Time entry." in response.text
    assert (
        "Ticket history now filters system-generated notes, including Workflow Rule title variants, "
        "and shows No Notes or No past entries "
        "when the selected ticket has no usable history."
    ) in response.text
    assert "Past time entry cards now show compact hours beside the resource name, such as 1.5hrs." in response.text
    assert "Full-browser navigation is now centered and uses the app&#39;s home-screen icon in the header." in response.text
    assert (
        "The work-entry navigation button now says Work, uses a work-entry icon, "
        "and the mobile top-bar buttons use the same blue style as the full web nav."
    ) in response.text
    assert (
        "Work in Progress and Review detail now show the ticket title with the state pill beside it, "
        "center key field labels, and use matching action button sizes."
    ) in response.text
    assert (
        "Work in Progress active cards show the Work in Progress label again, "
        "and full-browser summary notes line up with the job date cards."
    ) in response.text
    assert "Web service and missing-page errors now match Job Logger&#39;s look and offer Back to Login or Back to Work." in response.text
    assert "Work entries can now be Time entries or customer-visible Ticket notes." in response.text
    assert (
        "Ticket note mode uses a required note title and note description "
        "instead of time and Remote/On-Site fields."
    ) in response.text
    assert (
        "Append to resolution is available for both entry types, "
        "and submitted Ticket notes can be updated or deleted from Review."
    ) in response.text
    assert "Ticket notes now open from the selected ticket in a closeable newest-first overlay." in response.text
    assert (
        "A Past time entries button now opens ticket time entries with clear technician names, "
        "large time details, and summary-of-work details."
    ) in response.text
    assert "Work entry save, recording, and AI Cleanup messages now share one status line." in response.text
    assert (
        "Job date controls now center the date with Today, Yesterday, or Tomorrow "
        "inside the selector when applicable."
    ) in response.text
    assert "Ticket note fields are tighter, with Append to resolution below the note description." in response.text
    assert "Full-browser navigation now uses raised blue icon buttons with visible labels." in response.text
    assert "Buttons now have clear hover and pressed states, including red destructive actions staying red on hover." in response.text
    assert (
        "Work in Progress and Review now have clean time controls, larger Remote/On-Site pills, "
        "and rounded total time shown."
    ) in response.text
    assert "Full-browser Review now keeps Entry type beside Job date so start and end times share a row." in response.text
    assert "Review, Home, and header polish" in response.text
    assert "Review summaries now start with Remote. or On-Site. before the work notes." in response.text
    assert "The Home start button now says Start Work." in response.text
    assert "Work in Progress and Review job dates now show Today or the weekday beside the date." in response.text
    assert "Service-call date selectors now show Today, Yesterday, or Tomorrow with the weekday." in response.text
    assert "Dev builds now show DEV inside the yellow version badge instead of a separate pill." in response.text
    assert "Review is now titled Work Review and no longer shows the Autotask time-entry ID." in response.text
    assert "Review detail spacing and the mobile DEV version badge now fit better." in response.text
    assert "AI cleanup, speech-to-text, and sign-in updates" in response.text
    assert "AI Cleanup can now switch to Revert cleanup and restore the pre-cleanup notes after reloads." in response.text
    assert "Revert cleanup drafts now expire automatically instead of being kept forever." in response.text
    assert "Submitted Review entries can keep cleaned draft notes until Submit changes is clicked." in response.text
    assert "Speech-to-text can now use a trusted remote faster-whisper server." in response.text
    assert "Sign-in now temporarily blocks repeated failed attempts before checking another password." in response.text
    assert "Login protection, Work in Progress controls, and deployment safety" in response.text
    assert "Review visibility and Work in Progress refinements" in response.text
    assert "Review rows now show whether each job is Remote or On-Site." in response.text
    assert "Review detail can now switch Remote or On-Site and updates the Summary notes prefix." in response.text
    assert "Work in Progress active job cards are easier to tell apart." in response.text
    assert "Dev builds can now show a yellow DEV badge in the top bar." in response.text
    assert "Status pills now use a cleaner outlined all-caps style." in response.text
    assert "Full browser Work in Progress actions now keep finish and delete buttons directly under Record and AI Cleanup." in response.text
    assert "Work in Progress now has an editable Job date calendar." in response.text
    assert "Review detail can choose a client when an active entry was opened before a client was selected." in response.text
    assert "Client selection now requires choosing an Autotask search result on Work in Progress and Review." in response.text
    assert "Review client search no longer shows a Summary notes warning while typing." in response.text
    assert "Choosing an open ticket now locks that job&#39;s client name everywhere." in response.text
    assert "Mobile Review status messages now stay below the action buttons." in response.text
    assert "Service-call starts now hide tickets already marked Complete in Job Logger." in response.text
    assert "Submitted Review entries now use a clearer Submit changes button." in response.text
    assert "User management rows now fit better on full browser screens." in response.text
    assert "User management, ticket status, and Device sign-in updates" in response.text
    assert "User management rows are more compact and easier to scan." in response.text
    assert "Passkey setup and login buttons now use the clearer Device sign-in name." in response.text
    assert (
        "Submitted time entries now keep the Autotask ticket status matched to the selected Job Logger "
        "status on submit and Edit Entry."
    ) in response.text
    assert "If Delete From Autotask fails, Review can now offer a local-only purge option for the Job Logger entry." in response.text
    assert "Review action cleanup" in response.text
    assert "Review detail now uses compact action rows like Work in Progress." in response.text
    assert "Record and AI Cleanup now share a row on review detail with shorter labels and icons." in response.text
    assert "Active jobs can now be ended from Review detail." in response.text
    assert "Full browser Work in Progress and Review buttons now use cleaner paired rows." in response.text
    assert "Autotask submission now handles tickets that provide an assigned resource but omit the assigned role." in response.text
    assert "Autotask submission now handles tickets where the submitting user is assigned as a secondary resource." in response.text
    assert (
        "Autotask submission can now use a configured default service-desk role for a user "
        "when a ticket does not provide usable role data."
    ) in response.text
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
    v120_index = response.text.index(CURRENT_WEB_TITLE)
    v116_index = response.text.index("Review, Home, and header polish")
    v115_index = response.text.index("AI cleanup, speech-to-text, and sign-in updates")
    v114_index = response.text.index("Login protection, Work in Progress controls, and deployment safety")
    v113_index = response.text.index("Review visibility and Work in Progress refinements")
    v112_index = response.text.index("User management, ticket status, and Device sign-in updates")
    v111_index = response.text.index("Review action cleanup")
    v110_index = response.text.index("Direct submission and passkeys")
    v102_index = response.text.index("Autotask workflow and desktop layout updates")
    v101_index = response.text.index("Mobile shell navigation and close behavior")
    v100_index = response.text.index("Initial release")
    assert v120_index < v116_index
    assert v116_index < v115_index
    assert v115_index < v114_index
    assert v114_index < v113_index
    assert v113_index < v112_index
    assert v112_index < v110_index
    assert v111_index < v110_index
    assert v110_index < v102_index
    assert v102_index < v101_index
    assert v101_index < v100_index
    assert f'<h2 id="current-version-heading">{CURRENT_WEB_TITLE}</h2>' in response.text
    assert '<span class="release-version">v1.2.0</span>' in response.text
    assert '<span class="release-version">v1.1.6</span>' in response.text
    assert '<span class="release-version">v1.1.5</span>' in response.text
    assert '<span class="release-version">v1.1.4</span>' in response.text
    assert '<span class="release-version">v1.1.3</span>' in response.text
    assert '<span class="release-version">v1.1.2</span>' in response.text
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
    assert "v1.1.4" in response.text
