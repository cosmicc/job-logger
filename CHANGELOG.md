# Changelog

All notable changes to Job Logger are documented in this file.

## v1.0.1 - Mobile shell navigation and close behavior

- Added a managed-web-user-only Config gear icon to the phone-sized
  authenticated top bar so mobile users can reach `/config` when the full
  desktop navigation is hidden.
- Changed the mobile X close action so standalone PWA mode self-targets the
  current window before requesting close, while regular phone browser mode and
  blocked close requests fall back out of the app surface to `about:blank`
  without logging out or navigating through app routes.

## v1.0.0 - Initial release

- Initial release.
