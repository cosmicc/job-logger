# Changelog

All notable changes to Job Logger are documented in this file.

## v1.0.1 - Mobile shell navigation and close behavior

- Added a managed-web-user-only Config gear icon to the phone-sized
  authenticated top bar so mobile users can reach `/config` when the full
  desktop navigation is hidden.
- Changed the mobile X close action to use direct app-shell close behavior
  first, then fall back out of the app surface to `about:blank` if the browser
  keeps the page visible.
- Changed the authenticated phone top bar to show the version link, Home,
  Review, Config, and close icons while hiding the brand mark and logout button
  on phone-sized layouts.
- Added the current release's change list to the web changelog's current-version
  panel so each released version has visible notes in both `CHANGELOG.md` and
  `/changelog`.
- Added `WEB_CHANGELOG.md` as the concise source for `/changelog` so the web
  page can show quick user-facing summaries while this changelog keeps more
  detailed release notes.

## v1.0.0 - Initial release

- Initial release.
