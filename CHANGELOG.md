# Changelog

All notable changes to Job Logger are documented in this file.

## v1.0.2 - Autotask workflow and desktop layout updates

- Renamed the work-entry route from `/mobile` to `/home` so the URL no longer
  implies a phone-only page. The old `/mobile` route and service-call endpoint
  now redirect to `/home` for existing bookmarks.
- Removed the global `AUTOTASK_IMPERSONATION_RESOURCE_ID` setting from Docker,
  sample environment, application config, and the Autotask discovery helper.
  User-scoped Autotask calls now derive `ImpersonationResourceId` from the
  owning managed web user's Autotask resource ID.
- Fixed submitted Autotask **Edit Entry** updates for jobs whose ticket was
  already Complete by moving the ticket to In progress before the time-entry
  patch and restoring the selected final status afterward.
- Added automatic `New` to `In progress` ticket status updates when work starts
  from a selected Autotask ticket or service call.
- Added an editable ticket status field to the mobile Work in Progress page and
  blocking status overlays while Autotask submission/update/delete tasks run.
- Added Remote/On-Site labels and matching color treatment to open-ticket
  choices so ticket lookup is visually consistent with service-call starts.
- Moved managed-user password requirements into the `/config` password card and
  removed the redundant Current settings card.
- Improved the full browser `/home` home and Work in Progress layouts through
  desktop-only CSS so phones keep the existing touch-first layout.

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
- Tightened the phone-sized home page by removing redundant top labels above
  the start-work panel and moving the main work-entry card closer to the app
  header.

## v1.0.0 - Initial release

- Initial release.
