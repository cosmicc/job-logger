# Changelog

All notable changes to Job Logger are documented in this file.

## v1.1.7 - Admin health alerts

- Advanced the source-controlled dev runtime version to `v1.1.7`, including
  the Python package metadata and PWA service worker cache version.
- Added an admin-only red health alert button to the authenticated desktop and
  phone top bars. The alert links to Diagnostics and appears when cached app
  health reports degraded state, such as low disk space or Autotask API
  failures.
- Added cached Autotask API health tracking. A failed Diagnostics connectivity
  test, time-entry submission/update/delete failure, or live Autotask provider
  request failure keeps the alert active until a later Autotask API request or
  connectivity test succeeds.
- Centralized Diagnostics disk-usage snapshot logic in the shared app-health
  service so the Diagnostics page and top-bar alert use the same warning and
  critical thresholds.

## v1.1.6 - Cloudflare block controls, Review, Home, and header polish

- Advanced the source-controlled dev runtime version to `v1.1.6`, including
  the Python package metadata and PWA service worker cache version.
- Added a Diagnostics Cloudflare blocked-IP form so authorized debug users can
  manually enter an IP address and reason for an app-managed Cloudflare block.
- Changed failed-login row Cloudflare block actions to carry a safe reason into
  the local `cloudflare_ip_blocks` row, Cloudflare rule note, and audit event.
- Changed automatic Cloudflare failed-login blocks to include their stored
  reason in the matching audit event.
- Changed Autotask-bound Review summary prefixes to use `Remote. ` and
  `On-Site. ` while keeping older `Remote`, `Remote:`, and `Remote -` style
  prefixes parseable when saving existing review text.
- Changed the Home blank-start button label to **Start Work** so the main
  action matches the rest of the work-entry workflow language.
- Changed Work in Progress and Review detail **Job date** labels to show
  `(Today)` for the current app-local date and the selected weekday otherwise.
- Changed both Home service-call date selectors to show relative labels like
  `Today (Saturday)` for today, yesterday, and tomorrow, while other dates show
  the full month, ordinal day, and weekday without the year.
- Changed dev-build headers to merge the separate `DEV` pill into the version
  badge, rendering the combined version marker as one yellow badge.
- Changed Review to use the **Work Review** page title, tightened selected-job
  work-type/status spacing, and stopped showing the Autotask time-entry ID on
  submitted job details.
- Tightened the Diagnostics and Work Review page-header spacing, left-aligned
  the selected Review job status pill, centered the selected Review work-type
  switch, and nudged the phone DEV version badge left so it has more room
  beside the mobile action icons.
- Changed mobile Diagnostics Autotask submission-attempt and automatic-backup
  tables to keep full-width rows inside horizontal scrollers, and tightened the
  automatic-backup enabled/disabled status spacing.
- Renamed the authenticated header debug navigation item to **Diag** and
  retitled the debug page to **Diagnostics** with a broader page summary.

## v1.1.5 - AI cleanup revert, remote transcription, and login diagnostics

- Advanced the source-controlled dev runtime version to `v1.1.5`, including
  the Python package metadata and PWA service worker cache version.
- Added a persistent **Revert cleanup** state for Work in Progress and Review
  AI Cleanup. After cleanup succeeds, the button switches to **Revert cleanup**
  and can restore the pre-cleanup notes after page reload or navigation.
- Added `AI_CLEANUP_REVERT_RETENTION_HOURS`, defaulting to 24 hours, so stored
  pre-cleanup notes and submitted Review cleanup drafts are minimized
  automatically instead of being retained indefinitely.
- Added job-level database fields and migration `0016_ai_cleanup_revert_state`
  for AI cleanup undo state, with full-backup restore compatibility for older
  backups that do not contain those columns.
- Added a pending cleaned-summary draft for submitted Review entries so
  cleaned text can survive reloads without patching Autotask until the user
  clicks **Submit changes**.
- Added metadata-only audit events for cleanup reverts without storing raw
  summary text in audit details.
- Condensed the super-admin Diagnostics Autotask configuration snapshot,
  tightened the full-backup and automatic-backup panels, and shortened visible
  automatic-backup filenames while keeping full filenames available on hover.
- Changed the Diagnostics backup metadata cards so full-backup upload limit
  and restore scope share one compact row, while automatic backups show the
  backup directory beside the retention policy.
- Added automatic-backup source metadata so Diagnostics can label retained
  backups created at app startup separately from hourly scheduler backups.
- Added `TRANSCRIPTION_PROVIDER=faster_whisper_remote` for calling a trusted
  remote faster-whisper API while keeping `faster_whisper` as the local
  container-based option.
- Added remote faster-whisper Docker/runtime settings:
  `FASTER_WHISPER_REMOTE_URL`, `FASTER_WHISPER_REMOTE_API_KEY`, and
  `FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS`.
- Restricted remote faster-whisper HTTP URLs to loopback or private-network
  hosts; public remote transcription endpoints must use HTTPS.
- Changed successful-login Diagnostics rows to show `Password` and `Passkey`
  as colored status pills for quicker scanning.
- Added a default-off managed web-user Admin flag on `/users` that grants full
  `/debug` Diagnostics access, including existing buttons and options, without
  granting `/users`, super-admin review scope, or extra job workflow
  permissions.
- Added migration `0017_web_user_debug_admin` and full-backup restore
  compatibility so older backups restore managed users with Diagnostics admin
  access disabled.
- Added local pre-authentication login lockout after
  `CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS` failures for the same trusted
  enforcement IP and submitted username. The lockout lasts
  `LOGIN_LOCAL_LOCKOUT_MINUTES`, defaulting to 15, and applies even when
  Cloudflare auto-blocking is disabled or the Cloudflare API is unavailable.
- Added migration `0018_login_counter_lockout` so failed-login
  counters are scoped by trusted enforcement IP plus username, with full-backup
  restore compatibility for older counter rows.
- Changed automatic and manual Cloudflare failed-login blocks to use the trusted
  enforcement IP instead of the display-only client IP, and changed nginx to
  replace incoming `X-Forwarded-For` with a sanitized tunnel client IP.
- Changed Docker Compose and runtime validation to fail closed for production:
  Compose now requires `APP_SECRET_KEY`, `APP_PASSWORD`, and
  `POSTGRES_PASSWORD`; defaults to loopback nginx binding, secure session
  cookies, and Cloudflare Access enabled; and the app refuses production
  startup when secure cookies, non-default/non-placeholder secrets, or live
  Autotask are missing.
- Changed production startup validation so `CLOUDFLARE_ACCESS_REQUIRED=false`
  no longer prevents the app from starting. Docker Compose still defaults the
  optional Cloudflare Access header gate to enabled for internet-facing
  deployments.
- Added production `Strict-Transport-Security` response headers.

## v1.1.4 - Login protection, Work in Progress controls, diagnostics, and deployment safety

- Advanced the source-controlled dev runtime version to `v1.1.4`, including
  the Python package metadata and PWA service worker cache version.
- Added super-admin `/debug` controls to hide individual failed-login rows
  while preserving the raw JSONL audit download.
- Added app-managed Cloudflare zone IP Access Rule blocking for failed-login
  client IPs, including per-row block/unblock buttons, a Cloudflare blocked IP
  card, an allowlist for trusted IPs/CIDRs, and automatic blocking after the
  configured consecutive-failure threshold.
- Added persistent failed-login counters that reset to zero after a successful
  password or Device sign-in login from the same displayed client IP.
- Added Docker/runtime configuration for app-managed Cloudflare blocking:
  `CLOUDFLARE_IP_BLOCKING_ENABLED`, `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_IP_BLOCK_ALLOWLIST`, and
  `CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS`.
- Added database tables and migration coverage for app-managed Cloudflare
  blocks, hidden failed-login rows, and login-failure counters, with
  full-backup restore compatibility for older backups that do not contain
  those tables.
- Added Docker/runtime `BIND_ADDRESS` and `HTTP_PORT` support for the nginx
  listener so the host-networked Cloudflare Tunnel connector can target a
  loopback origin on a chosen port; `NGINX_PUBLIC_PORT` remains a
  backward-compatible fallback.
- Changed the super-admin Diagnostics disk-space card to combine monitored
  paths when used space and total space match exactly, reducing duplicate
  storage rows on single-drive installs.
- Changed the Diagnostics app log preview to show the newest 10 sanitized lines
  and moved Automatic database backups below the app log card.
- Added 10-row pagination for Autotask submission attempts, matching the
  existing paginated login-failure and Cloudflare blocked-IP tables.
- Moved the **Test Autotask API** action into the lower Autotask configuration
  card so the test control lives next to the related result and settings.
- Changed the login page so **Device sign-in** appears under the password
  sign-in button, removed the extra sign-in heading copy, and centered a
  non-clickable `JL` mark in the unauthenticated header.
- Changed Work in Progress **Rounded start** and **Rounded stop** controls to
  use editable 12-hour time fields like Review detail, while keeping the `-15`
  and `+15` controls and saving through server-validated active-job routes.
- Enlarged the Remote/On-Site pill switch treatment across Work in Progress and
  Review so the selected work-location control is easier to tap and scan.
- Changed Work in Progress and Review ticket description cards to stay visible
  for selected tickets that have no Autotask description, showing a clear
  left-aligned no-description message instead of hiding the card.

## v1.1.3 - Review visibility and Work in Progress refinements

- Advanced the source-controlled dev runtime version to `v1.1.3`, including
  the Python package metadata and PWA service worker cache version.
- Added Remote/On-Site work type to each row in the Review job list so
  reviewers can scan location context before opening a job.
- Added a Remote/On-Site switch to Review detail. Changing the switch updates
  the visible `Remote` or `On-Site` prefix at the start of Summary notes, and
  the existing review save, accept, retry, and submitted-entry update paths
  continue to parse that prefix back into the stored work-location mode.
- Changed Work in Progress active-job cards to use distinct slot shading for
  Job 1 and Job 2, making concurrent active entries easier to distinguish.
- Added a Docker/runtime `DEV_BUILD=true` flag that shows a small yellow
  `DEV` badge in the authenticated desktop and mobile header so dev instances
  are visually distinct from production.
- Changed shared status chips to use a consistent outlined, all-caps pill
  treatment while preserving the existing status color meanings.
- Changed the full browser Work in Progress action order so **End Work** or
  **Submit to Autotask** and **Delete** sit directly under **Record** and
  optional **AI Cleanup**, with recording and cleanup status text below all
  action buttons.
- Changed active Work in Progress cards to show an editable **Job date**
  calendar field instead of the raw started timestamp. The selected local date
  is saved through the existing active-job autosave path and carries into
  Review and Autotask submission.
- Changed phone-sized Review detail so Record Audio and AI Cleanup status text
  appears below the Review action buttons instead of between the summary tools
  and submit/delete controls.
- Added an Autotask company search field on Review detail when an active job
  has no client selected yet. Review uses the same server-backed client search
  rules as Work in Progress, verifies the selected Autotask company ID and
  display name before saving, rejects typed-only or mismatched client names,
  and audits the first saved client/company before normal Review ticket lookup.
- Changed Work in Progress and Review client locking so choosing an open ticket
  makes the stored client name read-only everywhere for that job.
- Fixed Review client search so typing a client no longer triggers generic
  review autosave or shows the Summary notes required warning; that empty-note
  warning is reserved for AI Cleanup or workflow actions that actually require
  notes.
- Changed service-call loading and service-call start verification to hide or
  reject service-call tickets when the current managed web user already has a
  local Job Logger time entry for the same ticket with ticket status
  **Complete**, including unsubmitted review entries.
- Changed the submitted Review detail update button text from **Edit Entry** to
  **Submit changes** while keeping the existing external Autotask update route
  and audit behavior.
- Added nullable managed-user `last_login_at_utc` metadata, stamped on
  successful password or Device sign-in login and shown in the `/users` table.
  The new migration and full-backup restore compatibility default older backups
  to no recorded last login.
- Added green/red Device sign-in key icons to the super-admin `/users` table so
  operators can see whether each managed web user has a registered passkey
  without exposing credential details.
- Changed the full-browser `/users` layout to give the managed-user table the
  full panel width, tighter fixed columns, compact icon controls, and
  ellipsized long values so each row fits cleanly.
- Added per-file **Download** buttons for retained automatic backups on
  `/debug`, using the same strict filename validation and sensitive-backup
  `no-store` response behavior as restore/download paths.
- Added Docker/runtime `LOG_LEVEL` support for `${LOG_DIR}/app.log`, limited to
  `DEBUG`, `INFO`, `WARNING`, or `ERROR`, with Docker defaulting to `INFO`.

## v1.1.2 - User management, ticket status, and Device sign-in updates

- Advanced the source-controlled runtime version to `v1.1.2`, including the
  Python package metadata and PWA service worker cache version.
- Changed the super-admin `/users` table to make the managed-user name and
  username columns easier to read in the desktop table by tightening table
  padding, reallocating column widths, and allowing those identity values to
  wrap instead of clipping.
- Changed the `/users` table's default service-desk role display to show only
  the numeric saved role ID. The add/edit role picker still keeps its
  explanatory labels for selection clarity.
- Removed the per-row Autotask Resource refresh action from `/users` and
  resized the action column for the remaining edit and enable/disable controls.
- Changed live Autotask time-entry submission so the selected Job Logger ticket
  status is required to sync to `Tickets.status` during submission. Submissions
  now fail with a clear configuration or permission error instead of creating a
  time entry while leaving the ticket in an old status such as New.
- Removed the `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED` runtime option. New
  submissions and submitted **Edit Entry** resubmissions now always reassert the
  selected Job Logger ticket status in Autotask, while ticket lookup and ticket
  selection remain read-only.
- Added a failed **Delete From Autotask** fallback dialog that can purge the
  local Job Logger review entry after a remote delete failure, with a local-only
  warning that the Autotask time entry may still exist.
- Renamed user-facing passkey action buttons and prompts to **Device sign-in**
  so users understand the feature can use a phone, browser, biometric unlock,
  PIN, or other passkey-capable device.

## v1.1.1 - Review cleanup, Autotask roles, Docker startup, and diagnostics

- Advanced the source-controlled dev runtime version to `v1.1.1`, including the
  Python package metadata and PWA service worker cache version.
- Changed Docker startup ordering so Compose and Portainer create the app,
  database, nginx, and tunnel containers without aborting the stack on an early
  healthcheck state. The app entrypoint still waits for PostgreSQL before
  migrations, and the database healthcheck keeps a longer first-start grace
  period for cold dev deployments.
- Added a super-admin Diagnostics disk-space monitor for the app filesystem,
  log directory, and backup directory, with warning and critical card states
  before monitored storage fills up.
- Changed review detail Summary notes controls so **Record** and optional
  **AI Cleanup** share the same compact two-button row, use leading icons, and
  no longer reserve empty status space while idle.
- Changed review detail workflow controls into a compact action stack with no
  more than two buttons per row. Submitted jobs pair **Edit Entry** with
  **Delete From Autotask**, normal unsubmitted jobs pair **Accept and Submit**
  with **Delete time entry**, and failed submissions keep retry/accept actions
  together while leaving destructive local delete on a separate row.
- Added **End Work** to review detail for active jobs, paired with **Delete time
  entry**, so work can be ended from the selected review pane without returning
  to the Work in Progress page.
- Changed the full browser Work in Progress and review detail button styling so
  paired action rows use matched widths and heights instead of leaving uneven
  spacing around primary and destructive actions.
- Changed Autotask ticket status writes to be opt-in with
  `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=false` by default. Time-entry
  submission and submitted-entry edits no longer require permission to patch
  `Tickets.status` unless that setting is explicitly enabled.
- Fixed Autotask submission for tickets that do not return
  `assignedResourceroleID` by using the ticket's `assignedResourceID` to resolve
  a default or single active service-desk role before falling back to the
  submitting managed user's service-desk role. The app still creates the time
  entry under the submitting managed user's Autotask resource ID.
- Fixed Autotask submission for tickets where the submitting managed user is a
  secondary resource by using the matching `TicketSecondaryResources.roleID`
  before generic Resource Service Desk Role fallbacks.
- Added an optional per-user default service-desk role on `/users`. Super
  admins can load active Autotask `ResourceServiceDeskRoles` for a user's
  Resource ID, choose a fallback role, and let Autotask submission use that
  explicit role when the selected ticket, secondary-resource assignment, and
  ticket-assigned resource do not provide a usable role.
- Changed the default service-desk role picker to show Autotask role names from
  `Roles.name` when available while still storing the selected numeric role ID
  on the managed web-user account.

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
- Changed the successful-login diagnostics table so config super-admin account
  chips are yellow and easier to distinguish from managed web-user logins.
- Added production/development branch workflow documentation describing
  `main` as the production branch, `dev` as the GitHub-tracked testing branch,
  and the required isolation for a separate dev deployment and Cloudflare
  Tunnel.
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
- Changed Ollama and LM Studio AI cleanup payloads to keep
  `AI_CLEANUP_INSTRUCTIONS` in each provider's system/control instruction field
  without duplicating those rules in the user-visible prompt.
- Changed the phone-sized top bar to use a CSRF-protected logout icon instead
  of the app-close X button.
- Changed active mobile Work in Progress controls so **Record** and
  **AI Cleanup** share a row, **End Work** and **Delete** share a row, all four
  actions use leading icons, and empty idle status space is removed.
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
