# Changelog

All notable changes to Job Logger are documented in this file.

## v1.1.0 - Direct submission, backups, and passkeys

- Added a default-off per-user **Submit from Work in Progress** setting on
  `/config`. When enabled, ending an active job submits the time entry directly
  to Autotask instead of requiring Review first.
- Kept Review available for submitted-entry edits and **Delete From Autotask**
  after direct submission, with the same idempotent Autotask submission service,
  audit events, CSRF checks, ownership checks, and local validation used by
  review acceptance.
- Added a database migration for the new user preference. Existing users keep
  the review-first workflow until they turn the setting on.
- Added automatic hourly full-database backups under the configured runtime
  backup directory, with retention for the newest 6 hourly backups plus one
  daily backup for today and each of the prior 2 days.
- Added a super-admin-only automatic backup section on `/debug` that lists
  retained backups and supports typed-confirmation restore from each file.
- Added `APP_SESSION_TIMEOUT_HOURS` so Docker deployments can control how many
  hours a local app login remains valid before the user must sign in again.
- Added managed-user WebAuthn/passkey support. Users can add a passkey after a
  normal password login, then use the device's normal unlock method for later
  sign-ins while password login remains available as the fallback.
- Added `WEBAUTHN_RP_NAME`, `WEBAUTHN_RP_ID`, and `WEBAUTHN_ORIGIN`
  configuration for passkey relying-party and origin validation.
- Changed the `/home` passkey setup card to appear only once after each
  successful managed-user login when that user has not set up a passkey, while
  keeping passkey setup always available on `/config`.
- Fixed passkey registration through Cloudflare/nginx by preserving the
  forwarded HTTPS scheme for WebAuthn origin derivation and logging safe
  origin/RP diagnostics when verification fails.
- Added remote work-location fallback from Autotask `Tickets.source` when
  ticket or service-call description detection has no Remote/On-Site result;
  `RMM Alert`, `Datto Alert`, `BCDR Alert`, and `Email Alert` are treated as
  Remote.
- Added a super-admin `/debug` successful-login card, pagination for successful
  and failed login cards, a successful-login JSONL download, and a newest-first
  app log tail card for quick operator diagnostics.
- Added a super-admin-only **Log out web users** control on `/debug` that
  invalidates all managed web-user sessions while leaving the current config
  super-admin session intact.
- Changed managed-user delete actions to disable the account, invalidate that
  user's existing signed sessions, and preserve the account row so the login
  screen can report that the account is disabled after the correct password is
  submitted.
- Fixed review detail for active jobs so the end-time field shows the current
  Work in Progress rounded stop preview while review saves continue to ignore
  that displayed end time until the job is actually ended.
- Moved ticket status underneath end time on review detail and aligned review
  open-ticket cards with Work in Progress ticket number, location, title,
  status, company, and color treatment.
- Changed service-call and open-ticket selection so they no longer patch
  Autotask ticket status before submission; they store verified ticket metadata
  locally and default the editable local ticket status to In progress.
- Changed Ollama and LM Studio AI cleanup URL validation to allow loopback,
  Docker host aliases, and private LAN IPs such as `172.25.x.x` while still
  rejecting public cleanup endpoints.
- Removed the full-page loading overlay from Work in Progress rounded start and
  rounded stop `-15` and `+15` adjustments so small time changes apply without
  the Autotask-style status overlay.
- Increased the default height of mobile Summary notes textareas while keeping
  them vertically resizable.
- Changed the web changelog current-version panel so the current release title
  uses the same heading style as older release titles.
- Improved the super-admin diagnostics login tables with shorter 10-row
  windows, clearer row formatting, icon-style extra-info buttons, and grouped
  proxy/request details.
- Changed login diagnostics to show the first `X-Forwarded-For` address as the
  client IP when present, while retaining direct socket and proxy header
  metadata for troubleshooting.
- Renamed the debug app-log card to **Application Log**, increased the tail to
  the newest 200 lines, and constrained the visible pane to about 20 scrollable
  lines.
- Fixed the new v1.1.0 migration identifiers so PostgreSQL can store them in
  Alembic's `version_num` column during Docker startup migrations.
- Clarified Cloudflare Tunnel setup to prefer the Compose-managed loopback
  Nginx origin instead of a changing LAN address.

## v1.0.2 - Autotask workflow and desktop layout updates

- Renamed the work-entry route from `/mobile` to `/home` so the URL no longer
  implies a phone-only page. The old `/mobile` route and service-call endpoint
  now redirect to `/home` for existing bookmarks.
- Removed the global `AUTOTASK_IMPERSONATION_RESOURCE_ID` setting from Docker,
  sample environment, application config, and the Autotask discovery helper.
  User-scoped Autotask workflows use the owning managed web user's Autotask
  resource ID in payloads and resource filters.
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
