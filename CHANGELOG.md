# Changelog

All notable changes to Job Logger are documented in this file.

## 1.3.0 - Admin contact, user management, review totals, and public-device sessions

### Added

- Added `ADMIN_CONTACT_EMAIL` as a Docker, Swarm, and `.env.example` setting
  for a safe end-user support contact address.
- Added a default-on **Send welcome email** option to the Add user form. The
  email includes the Job Logger link from `APP_PUBLIC_BASE_URL`, username,
  temporary-password instructions, mobile install steps, Device sign-in
  guidance, and the configured admin contact email when available.
- Added `/users` row actions that let the config super admin send a managed
  user a password reset email or resend the welcome email without exposing
  internal Autotask resource or role IDs in the user list.
- Added `/users` row delete actions for managed web users, including disabled
  rows.
- Added centered compact boxed Work today/week hour summaries, same-sized Review
  today/week total cards, and Review day-hours and week-hours columns
  calculated per job owner and local job date.
- Added 10-row newest-first Review job-list pagination.
- Added a default-off **This is a public device** login option for password
  sessions. Public-device sessions expire after 15 minutes of inactivity,
  disable the Device sign-in button while checked, and cannot start new Device
  sign-in setup.
- Added temporary success/failure overlays for `/users` password-reset email
  and welcome-email row actions.

### Changed

- Advanced the source-controlled dev runtime version to `v1.3.0`, including
  the Python package metadata and PWA service worker cache version.
- Changed disabled managed-user password-login, stale-session, Work page, and
  Device sign-in messages to show the configured admin contact email after the
  app has verified the account is disabled.
- Changed AI Help answers to append `If you need further help, contact
  <admin email>` below the answer, separated by a blank line, when
  `ADMIN_CONTACT_EMAIL` is configured.
- Changed account email delivery so password-reset and welcome emails share the
  same SMTP or SMTP2GO transport, provider result handling, and redacted error
  reporting.
- Changed the `/users` list to hide internal Autotask resource ID and role ID
  values while keeping email, role label, login status, Device sign-in status,
  Admin status, and account actions visible.
- Changed managed-user deletion so accounts with no jobs are fully removed,
  while accounts with linked jobs are hidden, signed out, stripped of passkeys,
  reset tokens, and preferences, and restored automatically when a new user is
  added with the same Autotask resource ID.
- Changed Home service-call options to hide tickets already marked Follow up in
  Job Logger, matching the existing Complete ticket filtering.
- Changed admin-sent password reset links so they remain valid even when the
  public self-service forgot-password flow is disabled.
- Changed Diagnostics successful-login, failed-login, and Autotask
  submission-attempt lists to show 7 rows per page without a vertical table
  scrollbar.
- Changed the public-device login checkbox to appear below **Forgot password?**
  and moved its description into hover/title text.
- Changed the Device sign-in button so selecting **This is a public device**
  greys it out and prevents clicks until the checkbox is cleared.
- Changed password-reset and welcome emails to refer to the app as **Autotask
  Job Logger**, including the updated welcome-email invite sentence.

### Fixed

- Fixed disabled-account login guidance so users can see who to contact instead
  of a generic administrator reference when a support address is configured.
- Fixed new-user welcome handling so account creation still succeeds and shows
  the super admin a warning when the welcome email is skipped or cannot be sent.
- Fixed hours-worked displays so zero-minute totals render as `0 Hours` instead
  of disappearing.
- Fixed public-device sessions so they suppress the mobile Device sign-in setup
  prompt and reject new passkey registration attempts while signed in on a
  public device.
- Fixed full-browser Home start-work Service calls spacing by removing the
  divider line and tightening the Service calls title/date area without changing
  the phone layout.

## 1.2.4 - 07.10.2026 - Review activity cleanup, work minimums, password reset, Autotask throttling, and version polish

### Added

- Added optional self-service managed-user password reset behind
  `PASSWORD_RESET_ENABLED`, with Cloudflare Turnstile verification, generic SMTP
  delivery, HMAC-stored single-use token hashes, 24-hour default expiry, CSRF
  validation, reset request throttles, existing-session invalidation after
  success, and non-enumerating browser messages.
- Added `password_reset_tokens` and `password_reset_request_counters` tables for
  reset-token hashes and IP/email/account reset throttles.
- Added Docker Compose, Swarm, and `.env.example` settings for password reset,
  SMTP delivery, `APP_PUBLIC_BASE_URL`, and Turnstile.
- Added `MAIL_MODE=smtp2go` support for password-reset email delivery through
  SMTP2GO's HTTPS API using `MAIL_SMTP2GO_API_KEY`, while keeping
  `MAIL_MODE=smtp` as the default existing SMTP behavior.
- Added `AUTOTASK_MAX_CONCURRENT_REQUESTS` and
  `AUTOTASK_REQUEST_SLOT_TIMEOUT_SECONDS` runtime settings for live Autotask
  request throttling.
- Added a visible `job.autotask.submitted` job activity when a time entry or
  ticket note is successfully submitted to Autotask.

### Changed

- Advanced the source-controlled dev runtime version to `v1.2.4`, including
  the Python package metadata and PWA service worker cache version.
- Changed active browser summary-note autosaves so they update the job without
  writing `job.description.browser_text_saved` activity events.
- Changed review autosaves so they update the job without writing
  `job.review.saved` activity events.
- Documented that browser summary-note autosaves are excluded from the Review
  audit timeline while explicit workflow, transcription, review decisions,
  submission, and cleanup actions remain audited.
- Changed time-entry validation so Remote work requires at least 15 rounded
  minutes and On-Site work requires at least 1 rounded hour across active
  end-work, Review save/submit/retry, submitted-entry edits, and direct
  Work in Progress Autotask submission.
- Changed production startup validation so enabling password reset requires an
  absolute public base URL and configured SMTP mail. Turnstile site/secret keys
  are required only when `TURNSTILE_ENABLED=true`, and
  `TURNSTILE_ENABLED=false` no longer requires `DEV_BUILD=true`.
- Changed the login page to show **Forgot password?** only when self-service
  password reset is enabled.
- Changed the login page to show a small app version label directly under the
  sign-in card, using `vX.Y.Z-DEV` on development builds.
- Changed the full-browser authenticated header to show the app version under
  the left-side Job Logger title, using `vX.Y.Z-DEV` on development builds.
- Changed live Autotask REST calls to pass through a shared request limiter,
  defaulting to two concurrent calls and coordinating across PostgreSQL-backed
  app processes with advisory locks when they share the same database.
- Changed both changelog files to use applicable non-empty `Added`, `Changed`,
  and `Fixed` sections for every historical version while keeping the web page
  output limited to concise user-facing bullets.

### Fixed

- Hid legacy `job.description.browser_text_saved` rows from the Review audit
  timeline while preserving all other job activity and existing database
  history.
- Hid legacy `job.review.saved` rows from the Review audit timeline while
  preserving the historical audit rows in the database.
- Prevented reset emails for disabled users, unknown emails, and duplicate
  enabled-user email matches while keeping the same user-facing message.
- Fixed the forgot-password Turnstile widget to load Cloudflare's standard
  `api.js` script before explicit local rendering, retry the explicit
  `api.js?render=explicit` URL if that first load fails, show user-facing
  verification status, and keep the reset button disabled until Cloudflare
  returns a verification token.
- Removed the `turnstile.ready()` and implicit auto-scan timing paths that left
  the verification box blank on the deployed forgot-password page.
- Tightened password reset Turnstile server validation by rejecting oversized
  tokens before Siteverify and requiring Cloudflare's returned action and
  hostname to match the forgot-password flow and configured public URL.
- Fixed password reset request handling so deployments with
  `TURNSTILE_ENABLED=false` bypass Turnstile verification without requiring a
  development build while still using CSRF, throttles, generic reset responses,
  and HMAC-stored reset-token hashes.
- Added sanitized forgot-password Turnstile browser and Siteverify logging,
  including debug-level lifecycle metadata and warning-level browser failure
  events without logging raw tokens, emails, reset URLs, site keys, or secrets.
- Fixed the login page version label spacing so the version renders 6px below
  the sign-in card instead of being pushed down by stretched grid rows.
- Lowered the full-browser header version label a few pixels under the Job
  Logger title.
- Reduced the chance of Autotask **Thread Threshold Exceeded** notifications by
  validating the app's live Autotask concurrency cap between one and three
  calls and defaulting below the three-thread threshold.

## 1.2.3 - 07.05.2026 - Help navigation, AI Help and cleanup, changelog display, and Portainer env guidance

### Added

- Added authenticated `/help` and `/help/ask` routes for a stateless
  Gemini-backed end-user help assistant using Gemini's OpenAI-compatible
  chat-completions API. The assistant is available to every authenticated
  account only when configured through environment variables.
- Added `AI_HELP_ENABLED`, `AI_HELP_PROVIDER`, `GEMINI_MODEL`,
  `GEMINI_API_BASE`, `AI_HELP_MAX_TOKENS`, `AI_HELP_TEMPERATURE`, and
  `AI_HELP_INSTRUCTIONS` runtime settings to Compose, Swarm, and
  `.env.example`. `GEMINI_API_KEY` is reused for both Gemini cleanup and AI
  Help.
- Added consistent spacing between the Help page cards across phone and
  full-browser layouts.
- Added bounded local help context from `USER_MANUAL.md`,
  `WEB_CHANGELOG.md`, `AGENTS.md`, agent skill files, and selected app source
  files so the server can answer user-support questions without committing
  provider credentials.
- Added help-assistant guardrails that reject likely source-code,
  deployment, secret, or internal configuration questions, require CSRF on
  help questions, and avoid local database storage of prompts and answers.
- Added sanitized AI Help console logging for request receipt, validation
  failures, refused internal questions, Gemini request/response metadata,
  provider errors, timeouts, and successful answers using a per-request trace
  ID without logging API keys, prompts, full questions, source context, or
  answers.
- Added Help page guidance text, clear-on-next-question input behavior, and an
  operational-status card that shows generic degraded status to ordinary users
  while keeping specific health details limited to Diagnostics-authorized
  users.
- Added temporary-password enforcement for newly created or super-admin-reset
  managed users. Those users are forced through `/config/password` before using
  other app routes, and successful password changes clear the requirement.

### Changed

- Advanced the source-controlled dev runtime version to `v1.2.3`, including
  the Python package metadata and PWA service worker cache version.
- Replaced the authenticated header version/changelog badge with a Help
  button. Full-browser navigation now shows the help icon and **Help** label,
  phone-sized navigation shows the help icon, and dev builds mark the Help
  control in yellow while showing `DEV` on the Help page.
- Moved the shared header Help control beside logout on both desktop and phone
  layouts while keeping the primary route navigation grouped on the left or
  centered as appropriate for the viewport.
- Changed phone-sized navigation so Work and Review stay left-aligned while
  Help, Config, optional Diagnostics, and Log out are right-aligned in that
  order.
- Increased the phone-sized header navigation icons inside their existing
  compact buttons so Work, Review, Config, Diagnostics, Help, and Log out are
  easier to scan without changing the mobile header footprint.
- Changed the Help page **version changelog** control to open release notes in
  an authenticated overlay with an X close button while keeping `/changelog`
  available as the direct authenticated fallback route.
- Restyled the **version changelog** control as a raised button and tightened
  the phone-sized current-version card so the version and changelog button sit
  on one row.
- Tightened the Help page assistant layout with an **Ask AI for help** heading,
  a one-line question field that submits on Enter, and a status line directly
  under the question field beside the Ask button.
- Trimmed `GEMINI_API_KEY` when loading runtime settings and changed Gemini
  401/403 help failures to show bounded credential guidance instead of raw
  provider troubleshooting text.
- Changed Gemini AI cleanup to use the same OpenAI-compatible
  `GEMINI_API_BASE` endpoint setting as AI Help, removed the separate
  `GEMINI_CLEANUP_API_BASE_URL` setting, and kept `GEMINI_CLEANUP_MODEL` plus
  `AI_CLEANUP_INSTRUCTIONS` cleanup-specific.
- Increased phone-sized header navigation icons again and normalized every
  mobile nav icon to the same visible size inside its button, including
  degraded-health layouts.
- Documented Portainer stack environment troubleshooting for redeploy errors
  where `/data/compose/.../stack.env` contains copied comments, headings, or
  prose instead of only `KEY=value` environment lines.
- Changed AI Help assistant failures returned as `/help/ask` 400 responses to
  emit route-level `ERROR` logs with a trace ID, status code, error class, and
  bounded detail so provider/configuration problems are visible in app console
  output.
- Tightened AI Help answer guidance for broad/simple questions and added
  metadata-only cleanup for short dangling trailing fragments after complete
  sentences.
- Changed the Help page layout so **Ask AI for help** appears directly under
  the Help title, **Operational Status** follows it, and **Current version**
  sits as the last card below the operational status card.
- Removed the extra Help page subtitle and the redundant **Application status**
  eyebrow so the page uses the requested concise card headings.
- Changed the degraded-health top-bar icon into an authenticated Help link to
  **Operational Status**, using yellow for warning and red for critical while
  the Help status card also shows green for operational.
- Limited the post-login Device sign-in setup prompt to phone-sized Home
  layouts and changed the prompt dismissal so desktop visits do not consume the
  mobile-only nudge.
- Changed the Help page and changelog overlay to label released dates as
  `Released: MM.DD.YYYY` only when the version has a release date, and changed
  previous overlay entries from an indented timeline to full-width cards that
  match the current-version card.

### Fixed

- Fixed Gemini AI cleanup requests for the OpenAI-compatible Gemini endpoint
  by matching the working chat-completions payload shape used by AI Help.
- Fixed Gemini AI Help endpoint construction so `GEMINI_API_BASE` can be the
  documented OpenAI-compatible base URL or a full `.../chat/completions`
  endpoint without the app appending `/chat/completions` twice, and changed
  HTML 404 provider responses to show base-URL guidance.

## 1.2.2 - 07.03.2026 - Health alerts, app icon, user manual, and Swarm storage

### Added

- Added the supplied logo PNGs, SVG wrapper versions, and color palette
  reference under `docs/design/`.
- Added optional best-effort Pushover app-health notifications with
  `PUSHOVER_ENABLED`, `PUSHOVER_USER_KEY`, `PUSHOVER_APP_KEY`,
  `PUSHOVER_API_URL`, and `PUSHOVER_TIMEOUT_SECONDS` Docker/runtime settings.
  Notifications are sent when monitored health first degrades, when the active
  degraded issue set changes, and when all monitored checks are restored.
- Added `APP_HEALTH_MONITOR_INTERVAL_SECONDS`,
  `APP_HEALTH_DB_LATENCY_WARNING_MS`, `APP_HEALTH_DB_LATENCY_CRITICAL_MS`,
  `APP_HEALTH_DB_POOL_WARNING_PERCENT`, and
  `APP_HEALTH_DB_POOL_CRITICAL_PERCENT` runtime settings to Compose, Swarm,
  and `.env.example`.
- Added a yellow or red Diagnostics app-health banner that summarizes active
  degraded-health issues at the top of the page.
- Added `USER_MANUAL.md` as a full managed-user manual for sign-in, Work in
  Progress, Review, Config, Device sign-in, changelog, and common messages.
- Added optional `LOG_DIR` file logging for the app while keeping redacted
  stdout/stderr logs available for container log collectors.

### Changed

- Advanced the source-controlled dev runtime version to `v1.2.2`, including
  the Python package metadata and PWA service worker cache version.
- Replaced the app favicon, installed-app icon images, authenticated desktop
  header brand mark, and source-controlled PWA icon assets with the new Job
  Logger logo.
- Changed the PWA manifest and Apple touch icon references to dedicated
  `job-logger-install-icon-*` filenames that use the original icon-format Job
  Logger artwork full-frame, with the outside white source canvas replaced by
  the dark app-icon background. Removed maskable manifest icon advertisements
  so mobile launchers do not reuse or over-crop older icon assets.
- Changed `DEV_BUILD=true` so dev/test deployments suppress Pushover
  notifications even when `PUSHOVER_ENABLED=true`.
- Expanded the shared app-health snapshot to track disk space, cached Autotask
  operation failures, database availability, database query latency, database
  connection-pool pressure, active local login lockouts, and app-managed
  Cloudflare IP blocks.
- Clarified documentation for **Submit from Work in Progress** so it is
  described as direct Autotask submission from Work in Progress instead of a
  generic workflow availability toggle.
- Changed Docker Swarm deployment so app logs, nginx logs, cloudflared logs,
  automatic backups, and the local faster-whisper model cache bind to the
  shared Swarm storage path, defaulting to
  `/mnt/swarm-storage/job-logger`.
- Documented the NFS-backed Swarm storage layout and kept Swarm database state
  on the required remote PostgreSQL server instead of adding file-backed
  database storage to the stack.

### Fixed

- Filtered Autotask ticket notes whose titles start with `Some actions did not
  occur` out of selected-ticket history overlays.

## 1.2.1 - 07.03.2026 - Work in Progress, Review, and outage-page polish

### Added

- Added a `bundled-edge` Docker Compose profile so the bundled nginx and
  `cloudflared` services can be enabled or omitted together while
  `.env.example` keeps the current bundled behavior enabled by default.
- Added `JOB_LOGGER_BUNDLED_EDGE_REPLICAS` for Swarm external-edge deployments
  and documented an external nginx sample config that proxies to the app
  service from the same Swarm overlay network.

### Changed

- Advanced the source-controlled dev runtime version to `v1.2.1`, including
  the Python package metadata and PWA service worker cache version.
- Adjusted full-browser Review detail so **Entry type** sits beside **Work
  type**, **Job date** sits beside **Ticket status**, and the start/end time
  controls share equal-width rows. Remote/On-Site switch pills now match the
  Time entry/Ticket note switch size.
- Adjusted full-browser Review detail so **Client name** and **Ticket number**
  stay paired together above a new centered **Ticket name** card, and moved
  **Ticket notes** and **Past time entries** to the bottom of that ticket-name
  card directly above **Ticket description**.
- Adjusted full-browser Work in Progress cards so **Entry type** sits beside
  **Work type**, **Job date** sits beside **Ticket status**, start/end time
  controls share a row, duration is centered beneath the time row, and
  **Client name** sits beside **Ticket number** when a ticket is selected.
- Adjusted the full-browser Work in Progress left-side context cards so
  **Ticket name** now uses the existing full-width ticket-history card with
  **Ticket notes** and **Past time entries** still underneath, **Ticket number**
  uses the existing paired context-card slot beside **Client name**, and the
  desktop heading again shows the selected ticket name above those cards.
- Centered Work in Progress locked **Client name** card text, centered ticket
  status dropdown text on Work in Progress and Review, centered app date values
  inside Work in Progress and Review date selectors, and changed the duration
  label to **Work Duration** with a larger display treatment. Phone-sized Work
  in Progress now also centers the display-only **Client name** and **Ticket
  name** card titles and values.
- Reordered `/config` cards to show **Appearance**, **Password**, **Device
  sign-in**, then **Workflow**.
- Adjusted full-browser Diagnostics so **Disk space** and **Session controls**
  share one row above the **Database** card while preserving the stacked phone
  layout.
- Adjusted full-browser Diagnostics so the **Session controls** card stretches
  to the same row height as **Disk space**, removing the open blank area below
  the shorter card.
- Changed phone-sized Work in Progress and Review detail card order so **Entry
  type**, **Work type**, **Ticket status**, **Job date**, **Start time**, **End
  time**, and duration appear in that sequence while leaving other fields in
  their existing positions.
- Centered the phone-sized Review **Client name** card title and value to match
  the surrounding ticket identity cards.
- Changed the phone-sized **Past time entries** overlay on Work in Progress and
  Review so it fills the screen like the **Ticket notes** overlay.
- Moved selected ticket-history controls into the ticket identity cards: Work
  in Progress now shows **Ticket notes** and **Past time entries** under
  **Ticket name**, while Review keeps **Client name** and **Ticket number**
  together above **Ticket description** and places those buttons in a centered
  **Ticket name** card.
- Moved the `/debug` **Log out web users** button below the session-control
  explanatory text and centered it as a wider destructive action while keeping
  the existing managed-web-user-only invalidation behavior.
- Kept the Work in Progress client search editable after a client is selected
  but before a ticket is chosen, allowing users to switch to another verified
  client and load that client's open tickets.
- Changed Ticket note mode on Work in Progress and Review so **Work type**
  remains visible as a disabled, greyed-out card instead of disappearing when
  Remote/On-Site no longer applies.
- Simplified the temporary outage page by removing its app-header icon, title,
  description, and divider line, then tightening the card spacing around the
  remaining outage message.

### Fixed

- Fixed Work in Progress ticket-history refreshes so the first active job keeps
  **Past time entries** visible to the right of **Ticket notes** when the
  authenticated lookup returns rows.

## 1.2.0 - 07.02.2026 - Ticket note mode, ticket history, Work in Progress layout, navigation, and web-edge errors

### Added

- Added a shared 15-minute time dropdown for Work in Progress and Review
  start/end time fields, opening around the currently selected time while
  preserving the existing `-15` and `+15` controls.
- Added a database-unavailable limp mode that starts the web process even when
  PostgreSQL is unreachable, serves an app-styled **Service Temporarily
  Unavailable** page for DB-backed routes, retries `/login` automatically, and
  avoids exposing database, network, or code details in the browser.
- Added a Diagnostics **Database** card with display-safe connectivity status,
  query latency, backend/driver, migration revision, and connection-pool
  counters without exposing connection strings, hosts, usernames, passwords, or
  raw database errors.
- Added `docker-swarm.yml` for image-based Swarm deployments with a remote
  PostgreSQL `DATABASE_URL`, overlay networking, Cloudflare Tunnel service, and
  no bundled PostgreSQL service.
- Added `COMPOSE_PROFILES=local-db` support so Compose can either deploy the
  bundled PostgreSQL container or connect the app to a remote PostgreSQL server
  through `DATABASE_URL`.
- Added database connection-pool and connection-timeout environment settings
  for remote PostgreSQL deployments.
- Added app-styled nginx error documents for common 4xx and 5xx web errors,
  disabled nginx server tokens, and kept proxy-generated failures branded as
  the Job Logger web service instead of the stock server error page.
- Added app-styled FastAPI browser error pages for app-generated HTTP errors,
  including missing routes. Unauthenticated users get **Back to Login**,
  authenticated sessions get **Back to Work**, and JSON clients that request
  JSON keep the normal JSON error body.
- Added regression coverage for unauthenticated public-surface boundaries so
  workflow pages, helper endpoints, diagnostics, user management, changelog,
  generated API docs, and public health URLs stay behind login, passkey,
  private Docker networking, or nginx blocking as appropriate.
- Added a Time entry / Ticket note mode switch to Work in Progress and Review
  detail before Autotask submission. Ticket-note mode disables start/stop time
  controls, hides Remote/On-Site, changes finish and delete labels to note
  wording, and requires a note title above the note description.
- Added customer-visible Autotask `TicketNotes` submission, submitted-note
  update, and submitted-note delete support. Ticket notes send note title, note
  description, ticket status, and the append-to-resolution setting without
  sending time-entry-only fields.
- Added a default-on **Append to resolution** checkbox for both time entries and
  ticket notes, and send that value to Autotask during create and submitted
  update actions.
- Added job schema fields and migration `0019_entry_type_ticket_notes` for
  entry type, note title, and append-to-resolution, with full-backup restore
  compatibility for older backups.
- Added workflow and provider regression coverage for review-submitted ticket
  notes, direct Work in Progress ticket-note submission, submitted ticket-note
  update/delete, and append-to-resolution payload handling.
- Added a read-only Autotask ticket-notes overlay for Work in Progress and
  Review detail. The **Ticket notes** button stays hidden until a ticket is
  selected and the authenticated server-side provider confirms bounded notes
  exist for that ticket. Note selection cards now show only note titles, the
  selected note detail includes safe author metadata when Autotask returns it,
  and notes are ordered by created date/time with the newest first. Note
  selector cards are sized for two title lines and clamp longer titles inside
  the card.
- Added a read-only **Past time entries** overlay for Work in Progress and
  Review detail. The button stays hidden until a ticket is selected and the
  authenticated provider confirms bounded `TimeEntries` rows exist for that
  ticket. The list shows each resource first-name first with a larger
  single-line local start/stop time and hours row, and the selected detail
  shows a larger date/time row plus the summary of work.
- Added a red degraded-health status icon to the authenticated desktop and
  phone top bars. The icon appears for every signed-in user when cached app
  health reports degraded state, such as low disk space or Autotask API
  failures, and does not open Diagnostics.
- Added cached Autotask API health tracking. A failed Diagnostics connectivity
  test, time-entry submission/update/delete failure, or live Autotask provider
  request failure from any user keeps the indicator active until the same
  Autotask operation type succeeds again. Successful unrelated Autotask
  operations no longer clear a different active failure.
- Added centered rounded duration labels to Work in Progress and Review detail
  so the total time between the visible start and stop times appears under the
  time controls and updates as those times change. Work in Progress and Review
  keep the label on a separate centered row so full-browser start and end time
  fields stay aligned.

### Changed

- Advanced the source-controlled dev runtime version to `v1.2.0`, including
  the Python package metadata and PWA service worker cache version.
- Replaced native browser date pickers on Work in Progress, Review, and
  service-call date controls with the app's own calendar chooser using
  **Today**, **Cancel**, and **Set** controls.
- Changed Review entry-type switching so moving from Time entry to Ticket note
  removes the visible `Remote. ` or `On-Site. ` summary prefix, and switching
  back to Time entry reapplies the prefix that matches the selected work type.
- Changed Ticket note mode on Work in Progress and Review so **Job date**
  becomes **Note Date** and the start/end time controls are hidden instead of
  disabled while their values remain available if the entry switches back to
  Time entry.
- Changed **Past time entries** selection cards so the resource row shows a
  compact right-aligned hours label such as `1.5hrs`, while the card time
  range and selected detail content keep their existing source data.
- Centered the full-browser authenticated top navigation and replaced the
  desktop header's text-only `JL` mark with the same source-controlled app icon
  used for mobile home-screen installs.
- Removed the unauthenticated login page's top app mark so the sign-in form is
  the first visible login-page element.
- Changed the authenticated full-browser header image to use the maskable
  installed-app icon asset.
- Renamed the authenticated `/home` navigation item from **Home** to **Work**,
  changed its desktop and phone icon to a work-entry add icon, and changed
  phone top-bar navigation buttons to use the same blue treatment as the
  full-browser navigation buttons.
- Changed successful and failed app-login diagnostics from host-mounted JSONL
  files to sanitized database-backed `login_attempts` records, while keeping
  authenticated generated JSONL downloads available from Diagnostics.
- Changed app logging to stdout/stderr and removed the host-mounted app-log and
  login-log Docker variables so Compose and Swarm runtimes can collect logs
  through the container platform.
- Changed automatic backup storage to the `/data/backups` volume instead of the
  removed host-mounted log directory.
- Changed the detailed and web changelog headings to write version numbers
  without brackets or a `v`, include release dates in `MM.DD.YYYY` format, and
  render those dates on the authenticated changelog page.
- Changed the Docker entrypoint so failed startup database waits or migrations
  no longer stop the web container; pending migrations are retried by the app
  before normal DB-backed pages resume.
- Changed Work in Progress and Review detail headings to show the selected
  ticket title with the job state pill beside it instead of a separate
  **Selected job** label, centered the main field labels, renamed active
  rounded-time controls to **Start time** and **End time**, and made Review
  detail action buttons match Work in Progress sizing.
- Restored the **Work in Progress** label above active work entries and kept
  the full-browser Summary notes panel aligned with the top of the **Job
  date** card.
- Kept the full-browser Work page **Job date** card at the same width as
  surrounding cards while narrowing only the date selector inside the card.
- Aligned the full-browser Work page note-title and summary text boxes with
  the top of the active **Job date** or **Note Date** card.
- Centered Ticket note title labels and text fields on Work in Progress and
  Review detail across phone and full-browser layouts.
- Changed shared switch pills so Time entry and Remote selected states stay
  green while Ticket note and On-Site selected states are orange.
- Enlarged the active **Work in Progress** label and kept active save,
  recording, and AI Cleanup status text directly under the Work in Progress
  action buttons.
- Made empty **No Notes** and **No past entries** history buttons fully inert,
  with no hover styling or click handling.
- Changed the cached degraded app-health top-bar icon to render for every
  signed-in user as a non-clickable status indicator that does not open
  Diagnostics.
- Changed passkey origin troubleshooting text to refer to the web service/app
  containers instead of naming the reverse-proxy implementation in the
  user-facing error.
- Removed obsolete app host-header allowlist and alternate nginx bind/fallback
  port settings. Docker now publishes nginx only on localhost using
  `HTTP_PORT`, and the public browser URL should be configured with
  `WEBAUTHN_ORIGIN` when the app needs it.
- Changed Work in Progress and Review detail status feedback so **Changes
  saved**, recording, and AI Cleanup messages share one status line below the
  action buttons and replace each other instead of rendering in separate
  locations. Empty Review status space is hidden until a message exists.
- Changed Work in Progress and Review **Job date** controls so `(Today)`,
  `(Yesterday)`, or `(Tomorrow)` appears inside the date selector box when
  applicable. The date and relative label are centered together with two
  spaces between them, and other dates show only the centered selected date.
- Changed Work in Progress and Review ticket-note layout so **Append to
  resolution** sits below **Note description** and directly above the action
  buttons, keeping the note fields grouped without extra vertical gaps.
- Changed the full-browser authenticated top navigation to raised blue
  icon-and-text buttons, including a visible **Log out** label after the logout
  icon, with pressed-button feedback matching the phone header controls.
- Changed Work in Progress, Review, navigation, and Diagnostics controls so
  enabled buttons brighten on hover and workflow action buttons have clearer
  raised and pressed states. Diagnostics destructive buttons now hover to a
  brighter red instead of falling back to a neutral dark treatment.
- Centralized Diagnostics disk-usage snapshot logic in the shared app-health
  service so the Diagnostics page and top-bar indicator use the same warning
  and critical thresholds.

### Fixed

- Filtered Workflow Rule and Service Desk Notification rows out of selected
  ticket-note history, including note titles that start with Workflow Rule, and
  changed empty selected-ticket history lookups to show disabled **No Notes**
  or **No past entries** buttons after lookup.
- Fixed remote PostgreSQL startup and Alembic migrations so provider-style
  `postgresql://` and `postgres://` database URLs are normalized to the
  installed psycopg 3 SQLAlchemy driver instead of trying to import `psycopg2`.

## 1.1.6 - 06.29.2026 - Cloudflare block controls, Review, Home, and header polish

### Added

- Added a Diagnostics Cloudflare blocked-IP form so authorized debug users can
  manually enter an IP address and reason for an app-managed Cloudflare block.

### Changed

- Advanced the source-controlled dev runtime version to `v1.1.6`, including
  the Python package metadata and PWA service worker cache version.
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

## 1.1.5 - 06.26.2026 - AI cleanup revert, remote transcription, and login diagnostics

### Added

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
- Added automatic-backup source metadata so Diagnostics can label retained
  backups created at app startup separately from hourly scheduler backups.
- Added `TRANSCRIPTION_PROVIDER=faster_whisper_remote` for calling a trusted
  remote faster-whisper API while keeping `faster_whisper` as the local
  container-based option.
- Added remote faster-whisper Docker/runtime settings:
  `FASTER_WHISPER_REMOTE_URL`, `FASTER_WHISPER_REMOTE_API_KEY`, and
  `FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS`.
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
- Added production `Strict-Transport-Security` response headers.

### Changed

- Advanced the source-controlled dev runtime version to `v1.1.5`, including
  the Python package metadata and PWA service worker cache version.
- Condensed the super-admin Diagnostics Autotask configuration snapshot,
  tightened the full-backup and automatic-backup panels, and shortened visible
  automatic-backup filenames while keeping full filenames available on hover.
- Changed the Diagnostics backup metadata cards so full-backup upload limit
  and restore scope share one compact row, while automatic backups show the
  backup directory beside the retention policy.
- Restricted remote faster-whisper HTTP URLs to loopback or private-network
  hosts; public remote transcription endpoints must use HTTPS.
- Changed successful-login Diagnostics rows to show `Password` and `Passkey`
  as colored status pills for quicker scanning.
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

## 1.1.4 - 06.24.2026 - Login protection, Work in Progress controls, diagnostics, and deployment safety

### Added

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
- Added Docker/runtime `HTTP_PORT` support for the nginx listener so the
  host-networked Cloudflare Tunnel connector can target a loopback origin on a
  chosen port.
- Added 10-row pagination for Autotask submission attempts, matching the
  existing paginated login-failure and Cloudflare blocked-IP tables.

### Changed

- Advanced the source-controlled dev runtime version to `v1.1.4`, including
  the Python package metadata and PWA service worker cache version.
- Changed the super-admin Diagnostics disk-space card to combine monitored
  paths when used space and total space match exactly, reducing duplicate
  storage rows on single-drive installs.
- Changed the Diagnostics app log preview to show the newest 10 sanitized lines
  and moved Automatic database backups below the app log card.
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

## 1.1.3 - 06.23.2026 - Review visibility and Work in Progress refinements

### Added

- Added Remote/On-Site work type to each row in the Review job list so
  reviewers can scan location context before opening a job.
- Added a Remote/On-Site switch to Review detail. Changing the switch updates
  the visible `Remote` or `On-Site` prefix at the start of Summary notes, and
  the existing review save, accept, retry, and submitted-entry update paths
  continue to parse that prefix back into the stored work-location mode.
- Added a Docker/runtime `DEV_BUILD=true` flag that shows a small yellow
  `DEV` badge in the authenticated desktop and mobile header so dev instances
  are visually distinct from production.
- Added an Autotask company search field on Review detail when an active job
  has no client selected yet. Review uses the same server-backed client search
  rules as Work in Progress, verifies the selected Autotask company ID and
  display name before saving, rejects typed-only or mismatched client names,
  and audits the first saved client/company before normal Review ticket lookup.
- Added nullable managed-user `last_login_at_utc` metadata, stamped on
  successful password or Device sign-in login and shown in the `/users` table.
  The new migration and full-backup restore compatibility default older backups
  to no recorded last login.
- Added green/red Device sign-in key icons to the super-admin `/users` table so
  operators can see whether each managed web user has a registered passkey
  without exposing credential details.
- Added per-file **Download** buttons for retained automatic backups on
  `/debug`, using the same strict filename validation and sensitive-backup
  `no-store` response behavior as restore/download paths.
- Added Docker/runtime `LOG_LEVEL` support for `${LOG_DIR}/app.log`, limited to
  `DEBUG`, `INFO`, `WARNING`, or `ERROR`, with Docker defaulting to `INFO`.

### Changed

- Advanced the source-controlled dev runtime version to `v1.1.3`, including
  the Python package metadata and PWA service worker cache version.
- Changed Work in Progress active-job cards to use distinct slot shading for
  Job 1 and Job 2, making concurrent active entries easier to distinguish.
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
- Changed Work in Progress and Review client locking so choosing an open ticket
  makes the stored client name read-only everywhere for that job.
- Changed service-call loading and service-call start verification to hide or
  reject service-call tickets when the current managed web user already has a
  local Job Logger time entry for the same ticket with ticket status
  **Complete**, including unsubmitted review entries.
- Changed the submitted Review detail update button text from **Edit Entry** to
  **Submit changes** while keeping the existing external Autotask update route
  and audit behavior.
- Changed the full-browser `/users` layout to give the managed-user table the
  full panel width, tighter fixed columns, compact icon controls, and
  ellipsized long values so each row fits cleanly.

### Fixed

- Fixed Review client search so typing a client no longer triggers generic
  review autosave or shows the Summary notes required warning; that empty-note
  warning is reserved for AI Cleanup or workflow actions that actually require
  notes.

## 1.1.2 - 06.22.2026 - User management, ticket status, and Device sign-in updates

### Added

- Added a failed **Delete From Autotask** fallback dialog that can purge the
  local Job Logger review entry after a remote delete failure, with a local-only
  warning that the Autotask time entry may still exist.

### Changed

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
- Renamed user-facing passkey action buttons and prompts to **Device sign-in**
  so users understand the feature can use a phone, browser, biometric unlock,
  PIN, or other passkey-capable device.

## 1.1.1 - 06.21.2026 - Review cleanup, Autotask roles, Docker startup, and diagnostics

### Added

- Added a super-admin Diagnostics disk-space monitor for the app filesystem,
  log directory, and backup directory, with warning and critical card states
  before monitored storage fills up.
- Added **End Work** to review detail for active jobs, paired with **Delete time
  entry**, so work can be ended from the selected review pane without returning
  to the Work in Progress page.
- Added an optional per-user default service-desk role on `/users`. Super
  admins can load active Autotask `ResourceServiceDeskRoles` for a user's
  Resource ID, choose a fallback role, and let Autotask submission use that
  explicit role when the selected ticket, secondary-resource assignment, and
  ticket-assigned resource do not provide a usable role.

### Changed

- Advanced the source-controlled dev runtime version to `v1.1.1`, including the
  Python package metadata and PWA service worker cache version.
- Changed Docker startup ordering so Compose and Portainer create the app,
  database, nginx, and tunnel containers without aborting the stack on an early
  healthcheck state. The app entrypoint still waits for PostgreSQL before
  migrations, and the database healthcheck keeps a longer first-start grace
  period for cold dev deployments.
- Changed review detail Summary notes controls so **Record** and optional
  **AI Cleanup** share the same compact two-button row, use leading icons, and
  no longer reserve empty status space while idle.
- Changed review detail workflow controls into a compact action stack with no
  more than two buttons per row. Submitted jobs pair **Edit Entry** with
  **Delete From Autotask**, normal unsubmitted jobs pair **Accept and Submit**
  with **Delete time entry**, and failed submissions keep retry/accept actions
  together while leaving destructive local delete on a separate row.
- Changed the full browser Work in Progress and review detail button styling so
  paired action rows use matched widths and heights instead of leaving uneven
  spacing around primary and destructive actions.
- Changed Autotask ticket status writes to be opt-in with
  `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=false` by default. Time-entry
  submission and submitted-entry edits no longer require permission to patch
  `Tickets.status` unless that setting is explicitly enabled.
- Changed the default service-desk role picker to show Autotask role names from
  `Roles.name` when available while still storing the selected numeric role ID
  on the managed web-user account.

### Fixed

- Fixed Autotask submission for tickets that do not return
  `assignedResourceroleID` by using the ticket's `assignedResourceID` to resolve
  a default or single active service-desk role before falling back to the
  submitting managed user's service-desk role. The app still creates the time
  entry under the submitting managed user's Autotask resource ID.
- Fixed Autotask submission for tickets where the submitting managed user is a
  secondary resource by using the matching `TicketSecondaryResources.roleID`
  before generic Resource Service Desk Role fallbacks.

## 1.1.0 - 06.21.2026 - Direct submission, backups, and passkeys

### Added

- Added a default-off per-user **Submit from Work in Progress** setting on
  `/config`. When enabled, ending an active job submits the time entry directly
  to Autotask instead of requiring Review first.
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
- Added remote work-location fallback from Autotask `Tickets.source` when
  ticket or service-call description detection has no Remote/On-Site result;
  `RMM Alert`, `Datto Alert`, `BCDR Alert`, and `Email Alert` are treated as
  Remote.
- Added a super-admin `/debug` successful-login card, pagination for successful
  and failed login cards, a successful-login JSONL download, and a newest-first
  app log tail card for quick operator diagnostics.
- Added production/development branch workflow documentation describing
  `main` as the production branch, `dev` as the GitHub-tracked testing branch,
  and the required isolation for a separate dev deployment and Cloudflare
  Tunnel.
- Added a super-admin-only **Log out web users** control on `/debug` that
  invalidates all managed web-user sessions while leaving the current config
  super-admin session intact.

### Changed

- Kept Review available for submitted-entry edits and **Delete From Autotask**
  after direct submission, with the same idempotent Autotask submission service,
  audit events, CSRF checks, ownership checks, and local validation used by
  review acceptance.
- Changed the `/home` passkey setup card to appear only once after each
  successful managed-user login when that user has not set up a passkey, while
  keeping passkey setup always available on `/config`.
- Changed the successful-login diagnostics table so config super-admin account
  chips are yellow and easier to distinguish from managed web-user logins.
- Changed managed-user delete actions to disable the account, invalidate that
  user's existing signed sessions, and preserve the account row so the login
  screen can report that the account is disabled after the correct password is
  submitted.
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
- Clarified Cloudflare Tunnel setup to prefer the Compose-managed loopback
  Nginx origin instead of a changing LAN address.

### Fixed

- Fixed passkey registration through Cloudflare/nginx by preserving the
  forwarded HTTPS scheme for WebAuthn origin derivation and logging safe
  origin/RP diagnostics when verification fails.
- Fixed review detail for active jobs so the end-time field shows the current
  Work in Progress rounded stop preview while review saves continue to ignore
  that displayed end time until the job is actually ended.
- Fixed the new v1.1.0 migration identifiers so PostgreSQL can store them in
  Alembic's `version_num` column during Docker startup migrations.

## 1.0.2 - 06.20.2026 - Autotask workflow and desktop layout updates

### Added

- Added automatic `New` to `In progress` ticket status updates when work starts
  from a selected Autotask ticket or service call.
- Added an editable ticket status field to the mobile Work in Progress page and
  blocking status overlays while Autotask submission/update/delete tasks run.
- Added Remote/On-Site labels and matching color treatment to open-ticket
  choices so ticket lookup is visually consistent with service-call starts.

### Changed

- Renamed the work-entry route from `/mobile` to `/home` so the URL no longer
  implies a phone-only page. The old `/mobile` route and service-call endpoint
  now redirect to `/home` for existing bookmarks.
- Removed the global `AUTOTASK_IMPERSONATION_RESOURCE_ID` setting from Docker,
  sample environment, application config, and the Autotask discovery helper.
  User-scoped Autotask workflows use the owning managed web user's Autotask
  resource ID in payloads and resource filters.
- Moved managed-user password requirements into the `/config` password card and
  removed the redundant Current settings card.
- Improved the full browser `/home` home and Work in Progress layouts through
  desktop-only CSS so phones keep the existing touch-first layout.

### Fixed

- Fixed submitted Autotask **Edit Entry** updates for jobs whose ticket was
  already Complete by moving the ticket to In progress before the time-entry
  patch and restoring the selected final status afterward.

## 1.0.1 - 06.20.2026 - Mobile shell navigation and close behavior

### Added

- Added a managed-web-user-only Config gear icon to the phone-sized
  authenticated top bar so mobile users can reach `/config` when the full
  desktop navigation is hidden.
- Added the current release's change list to the web changelog's current-version
  panel so each released version has visible notes in both `CHANGELOG.md` and
  `/changelog`.
- Added `WEB_CHANGELOG.md` as the concise source for `/changelog` so the web
  page can show quick user-facing summaries while this changelog keeps more
  detailed release notes.

### Changed

- Changed the mobile X close action to use direct app-shell close behavior
  first, then fall back out of the app surface to `about:blank` if the browser
  keeps the page visible.
- Changed the authenticated phone top bar to show the version link, Home,
  Review, Config, and close icons while hiding the brand mark and logout button
  on phone-sized layouts.
- Tightened the phone-sized home page by removing redundant top labels above
  the start-work panel and moving the main work-entry card closer to the app
  header.

## 1.0.0 - 06.16.2026 - Initial release

### Added

- Initial release.
