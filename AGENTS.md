# AGENTS.md

## Project Overview

This repository is for a Dockerized Python web application named Job Logger.
The application provides a mobile-first web workflow for recording work time,
recording spoken job descriptions, reviewing recorded jobs, and creating
Autotask time entries after review and acceptance.

The application will be exposed through Cloudflare Tunnel using `cloudflared`.
The Docker deployment must include the Python web application, PostgreSQL, and
`cloudflared` when practical for local production deployment.

All design and implementation decisions must prioritize security first.

## Security Requirements

Security is the highest priority for this project.

Use both Cloudflare Access and application-level authentication.
Cloudflare Access protects the public hostname before traffic reaches the
application. The Python application must still enforce its own authenticated
server-side sessions and authorization checks.

`APP_USERNAME` and `APP_PASSWORD` define the config super admin. That account
is for user management, diagnostics, backup/restore, and read-only job review;
it must not start, edit, submit, delete, record, or AI-cleanup work entries
because it has no Autotask resource ID. Normal work must be performed through
database-managed web users created on `/users`.
Only the config super admin may see or access `/debug` and `/debug/*` routes;
managed web users must receive 403 for direct debug requests.

Managed web users must have a full name, unique username, password hash, and
Autotask resource ID. They may also store the email address returned by the
selected Autotask Resource lookup. The `/users` page presents managed accounts
in a table with visible stored email metadata and icon-only row actions for
refresh, edit, enable/disable, and delete-as-disable. The refresh action
re-queries Autotask Resources, requires the returned resource ID to match the
stored ID, and updates only safe local name/email metadata. The add form may
suggest usernames from full names, such as `jblow` for `Joe Blow`, and add/edit
forms may query Autotask Resources for a super-admin-only resource picker.
Store only salted password verifiers, never raw managed user passwords.
Managed-user passwords must be at least 8 characters and include lowercase,
uppercase, number, and symbol characters.
Disabled web users must be blocked from new logins and from using old signed
sessions. Deleting a web user from `/users` disables the account, invalidates
that user's signed sessions, preserves the row for audit/login-state clarity,
and lets the login screen explain that the account is disabled after the
correct password is submitted.

Local authenticated sessions must expire after `APP_SESSION_TIMEOUT_HOURS`,
measured in hours. The configured value controls both the signed session cookie
lifetime and the server-side authenticated-at timestamp check. Expired sessions
must be cleared and forced through login again.
The super-admin Diagnostics page may also invalidate all managed web-user
sessions with a CSRF-protected button. That action must not sign out the config
super admin because the super admin is not a managed web user.

Managed web users may register WebAuthn passkeys after a normal password login.
Passkeys are user-owned public credentials, not super-admin credentials. The app
stores only the public credential ID, public key, signature counter, and safe
device metadata; the private key and local unlock method stay on the user's
device or passkey provider. Passkey registration and login must use one-time
session challenges, require CSRF on browser fetches, require user verification,
verify the configured relying-party ID and origin, update signature counters on
successful login, block disabled users, audit only safe metadata, and keep
password login available as fallback.
`/config` is the persistent passkey management surface. `/home` may show an
Add Passkey card only once after each successful login, and only while that
managed user has no registered passkeys.

Managed web users may change per-login configuration on `/config`. Per-user
configuration is database-backed, defaults to the dark theme, saves immediately
when an option changes, and supports `dark` or `light` visual themes for all
authenticated mobile and web pages. It also supports the default-off **Submit
from Work in Progress** option. When enabled, ending an active job submits the
time entry directly to Autotask instead of stopping in Review first. The
password-change section on `/config` is the exception: it requires two matching
password entries and an explicit **Change password** submit button, and the
password card must show the managed-user password requirements. The config
super admin does not have user settings, does not see the Config menu item,
cannot access `/config`, and always renders in dark mode.

Never rely on the mobile UI, browser state, or hidden form fields for security
decisions. The server must validate authentication, authorization, CSRF tokens,
job ownership, workflow status, timestamps, ticket numbers, ticket statuses, and
all submitted text.

Store all secrets outside source control. Autotask credentials, transcription
provider credentials, session secrets, database passwords, Cloudflare Tunnel
tokens, and API keys must come from environment variables, Docker secrets, or
another approved secret store.

Do not log secrets, session tokens, raw authentication headers, Cloudflare Access
JWTs, Autotask API credentials, transcription provider credentials, raw audio,
or other sensitive values. Successful and failed app-login attempts may be
written to host-mounted JSONL login-attempt logs and shown on `/debug`, but only
with sanitized metadata such as timestamp, client IP, submitted username,
account kind, authentication method, user agent, request/proxy details, failure
reason, and password-present/length for failures. Never write or display the raw
submitted password. For login diagnostics, prefer the first `X-Forwarded-For`
address as the displayed client IP when present, while retaining the direct
socket peer and proxy headers as supporting metadata. The successful-login
window may visually distinguish config super-admin account-kind chips from
managed web-user chips, but must not expose extra sensitive metadata to do so.

Prefer secure defaults. Cookies must be HTTP-only, secure when served over HTTPS,
and SameSite-protected. Forms and state-changing requests must use CSRF
protection.

The application must maintain immutable audit events for important actions,
including job start, job end, description recording, transcription updates,
manual edits, review decisions, direct Work in Progress Autotask submission,
Autotask submission attempts, Autotask submission success, Autotask submission
failure, and authentication-sensitive events.

Raw audio must not be stored by default. If audio retention is ever added, it
must be explicit, configurable, documented, access-controlled, and auditable.

AI summary cleanup sends job summary text to the configured provider only when
`AI_CLEANUP_ENABLED=true` and `AI_CLEANUP_PROVIDER` is `gemini`, `grok`,
`ollama`, or `lm_studio`. Treat summary text as customer/work data. The server
must validate authentication and CSRF, bound input length, keep API keys,
provider URLs, and cleanup instructions server-side in Docker or environment
variables, set `store=false` on Gemini requests, constrain Ollama and LM Studio
cleanup URLs to loopback or private-network endpoints, send configured cleanup
instructions through the provider instruction field, and audit only metadata
such as provider, model, source, and text lengths. Do not store raw cleanup
prompts or full cleaned/uncleaned summaries in audit details.

## Core Workflow

The mobile web page must provide a quick active-job workflow with these actions:

- Start work.
- End work.
- Record description.

Description recording is available during an active job and on review detail
before the job has been successfully submitted to Autotask.

Recorded jobs follow this lifecycle:

1. A draft job is created when work starts.
2. The draft job is owned by the logged-in managed web user.
3. The active job is ended by the user.
4. With the default workflow setting, the job becomes available for that user
   to review. If the owning user enabled **Submit from Work in Progress**, the
   server validates the same required submission fields and submits the job
   directly to Autotask during end-work instead. The config super admin may view
   all jobs but cannot mutate them.
5. The review page allows time, status, and notes to be edited before
   acceptance while keeping the selected Autotask client and ticket read-only.
6. An accepted review job, or a directly submitted Work in Progress job, creates
   an Autotask time entry using the owning user's Autotask resource ID.
7. A successfully submitted Autotask job keeps ticket and client identity
   read-only. Its job date, start time, end time, summary notes, and ticket
   status can be changed only through the audited **Edit Entry** action, which
   updates the existing Autotask time entry instead of creating another entry.
   When `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=true`, **Edit Entry** may
   temporarily move a previously Complete ticket to In progress before patching
   `TimeEntries`, then move the ticket to the selected final status when
   needed. With ticket status updates disabled, **Edit Entry** patches only the
   existing `TimeEntries` row and never patches `Tickets.status`.
   The audited **Delete From Autotask** action may delete the external time
   entry and move the local job back to review, but must not delete the local
   job record.
8. Failed or edited jobs remain available for audit history. Local cleanup is
   available only through explicit audited delete actions, including **Delete
   time entry** on review detail for local unsubmitted jobs.

Jobs must never disappear silently. Destructive deletion should be avoided.
Prefer archived, superseded, or voided states with audit records.

## Time Rules

The application timezone is `America/Detroit` for all user-facing dates and
times. This is required so EST and EDT transitions are handled correctly.
User-facing times must display in 12-hour `am`/`pm` format, not 24-hour format.

Store timestamps in PostgreSQL in UTC. Convert timestamps to and from
`America/Detroit` at the application boundary for display, forms, reports, and
Autotask payload construction.

Job start times must round to the closest 15-minute interval.

Job end times and job duration must also round to 15-minute intervals.

Jobs do not span multiple work dates. Review forms must use one local job date
with start and end times, and must reject edits where the end time is not after
the start time on that same date.

Rounding behavior must be centralized in one tested time utility instead of
being duplicated across routes, templates, or Autotask integration code.

Daylight Saving Time edge cases must be considered when converting local times.

## Autotask Integration

Autotask time entries are created after review acceptance by default. A managed
web user can opt in to direct Work in Progress submission on `/config`, which
creates the Autotask time entry during end-work after the same local submission
requirements pass.

The required Autotask time-entry fields for this application are:

- Ticket number.
- Summary notes.
- Local ticket status selection.
- Date.
- Start time.
- End time.

Supported ticket status values are:

- In progress.
- Waiting customer.
- Waiting parts.
- Follow up.
- Complete.

Autotask submission must be idempotent. A retry must not create duplicate time
entries for the same accepted job.

Autotask resource IDs are not global configuration. They belong to managed web
users and are required before a user can start work. The app uses the logged-in
or owning user's resource ID for service-call lookup and for
`TimeEntries.resourceID` on create. User-scoped Autotask calls must not send
Autotask's optional `ImpersonationResourceId` header; do not add or restore a
global `AUTOTASK_IMPERSONATION_RESOURCE_ID` setting. Static Autotask role and
billing-code IDs must not be configured. Ticket status writes are opt-in
through `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED`; when disabled, submission and
submitted-entry edits must not patch `Tickets.status` and should create or
patch only `TimeEntries`. The live provider must query the selected ticket at
submission time, use `Tickets.assignedResourceroleID` as `TimeEntries.roleID`
when available, fall back to
`TicketSecondaryResources.roleID` for the submitting managed user's resource
when that user is a secondary resource on the ticket, then fall back to
`Tickets.assignedResourceID` to resolve that resource's default or single active
`ResourceServiceDeskRoles.roleID`, then fall back to the submitting managed
user's default or single active service-desk role when the ticket omits assigned
role context. The app must still send the submitting managed user's resource ID
as `TimeEntries.resourceID`. Omit `TimeEntries.billingCodeID` so Autotask
inherits the selected ticket's Work Type on create. API credentials, optional
ticket status IDs, the ticket-status-update switch, and time-entry type remain
environment configuration.
The super-admin `/users` page may query `/Resources/query` through the server
to find matching Autotask Resources by `Last, First` name and fill the
user-specific resource ID and optional email address. Per-row refresh on
`/users` uses the same server-side provider and updates stored local metadata
only after the returned resource ID matches the user's saved resource ID.

Autotask API errors must be recorded clearly for review and troubleshooting
without exposing credentials or sensitive protocol details.

## Speech-to-Text Requirements

Speech-to-text transcription must be configurable by provider.

The application should define a provider interface so transcription backends can
be changed without rewriting the job workflow.

The translated speech-to-text description must populate the editable job
description used on the review page.

After the user stops active-job or review-detail recording, the browser status
must distinguish the upload and transcription phases: first **Sending data to
server...**, then **Converting audio to text...**, then **Conversion
complete.** when the final transcript has been returned and pasted into the
summary field. Audio and AI Cleanup status lines are plain text only. The
spinning loading icon belongs in the active button itself, such as the disabled
active-job **Record** button while the recording is still being sent or
converted and the **AI Cleanup** button while cleanup is running.

The local faster-whisper provider may use `FASTER_WHISPER_INITIAL_PROMPT` to
guide transcript formatting, including rendering dictated punctuation words as
punctuation marks. Treat it as a best-effort model hint, not a validation or
security control.

AI summary cleanup is separate from speech-to-text. It sends the current
editable summary text to the configured server-side cleanup provider and
replaces the summary textarea with the returned cleaned text. It must not
submit to Autotask or bypass the configured finish/review workflow.

The review page must allow the transcribed description to be edited or
re-recorded before the job is accepted and submitted to Autotask.

Do not permanently store raw audio by default.

## Web Interface Requirements

The mobile interface must be optimized for quick use from a phone.
Mobile summary notes textareas should default to a taller note-taking area than
the shared desktop textarea baseline while remaining vertically resizable.

The `/home` route renders the Home and Work in Progress workflow. Full browser
rendering should use desktop-only CSS from `desktop.css` for a wider,
scan-friendly layout. Keep full-browser layout changes out of `phone.css` so
the installed mobile phone experience remains unchanged unless explicitly
requested. Do not use route names to select the mobile or desktop page version;
presentation must follow client/browser and media behavior.

Managed web-user pages must respect the current user's saved theme preference.
The default is the dark theme. Light theme support must cover mobile, review,
user management, config, debug, and login surfaces through shared CSS variables
instead of a separate unaudited template branch. Super-admin pages always use
dark mode.

On phone-sized authenticated layouts, the top bar hides the brand mark and the
desktop logout control. It shows only the discreet version link, compact
navigation icons, and a mobile logout icon button on the right. The version
link is centered between the left navigation group and the right action group.
Managed web users see Home and Review on the left, with Config and logout on
the right. The config super admin sees Users, Review, and Diagnostics on the
left, with logout on the right, and must not see the Config shortcut. The
mobile logout button must post to `/logout` with the rendered CSRF token and
must not use `window.close()` or a browser-only app close fallback. Full-width
`/home`, review, debug, and other non-mobile authenticated views still expose
the explicit desktop logout control.

The standard review interface must work well on a full computer screen.

The review interface must allow editing of reviewed job summary notes, ticket
status, date, start time, end time, and the translated speech-to-text
description before acceptance. The summary textarea must show the complete
Autotask summary that will be sent, including the leading Remote or On-Site
prefix. Saving review edits parses that prefix back into the stored
`work_location` field so the final payload can be corrected without exposing
ticket or client identity to edits. The selected Autotask client name, company
ID, ticket number, and ticket title are read-only identity fields populated from
Autotask lookup and must not be editable on the review page.
Work in Progress and review detail action controls should stay compact and
scannable on both phone and full browser layouts. Use paired button rows when
two actions naturally belong together, such as **Record** with **AI Cleanup**,
**End Work** with **Delete**, and review submit/edit actions with the matching
delete action. Never place more than two action buttons in one row.

All state-changing actions must be explicit and auditable.

Validation errors must be clear enough to fix the record without exposing
internal implementation details.

## Database Requirements

Use PostgreSQL for persistent storage.

Database schema changes must be tracked with migrations.

Important tables should include enough data to support job review, Autotask
idempotency, transcription status, per-user configuration, and immutable audit
history.

Database fields that represent timestamps must have clear UTC/local-time
handling documented in model comments, migration comments, and relevant utility
functions.

## Docker Requirements

The project must support Docker-based deployment.

Docker Compose should include the Python application, PostgreSQL, and
`cloudflared` when practical.

The application container should not run as root unless there is a specific,
documented reason.

Persistent PostgreSQL data must be stored in a Docker volume or another
documented persistent storage location.

Health checks should be added for services where practical.
PostgreSQL health checks must allow enough startup grace for first-time volume
initialization so Docker Compose or Portainer does not abort the app stack while
the database is still bootstrapping.
Compose dependencies should preserve container start order without using
`service_healthy` as a hard stack-creation gate; the app entrypoint owns the
database connectivity wait before migrations.

## Python Standards

Python code must follow PEP 8, except the line-length rule may be relaxed when
longer lines make the code clearer.

Use type hints for application code whenever practical.

Use descriptive names for modules, classes, functions, variables, database
columns, environment variables, and configuration settings.

Avoid shortcuts that make the application harder to audit, test, or maintain.
Prefer complete, explicit code over clever or compressed code.

## Documentation And Code Remarks

All code must be clear to read and thoroughly documented.

Use docstrings to explain modules, classes, public functions, services, and
security-sensitive logic.

Use comments to explain important variables, configuration values, workflow
states, validation decisions, security decisions, database fields, and external
API payload fields.

Comments must explain why important decisions are made, not only repeat what the
next line of code does.

When adding new environment variables, database tables, models, service classes,
routes, templates, or external API fields, document their purpose.

## Changelog Requirements

Every project must include a `CHANGELOG.md`.

All recorded changes must be documented by version or by push if the project is
not versioned yet.

Changes that affect security, database schema, Autotask integration, speech to
text, Docker deployment, authentication, or audit logging must be called out
clearly.

Every released version must update both the detailed source changelog and the
authenticated web changelog. `CHANGELOG.md` is the detailed operator and
agent-facing record. `WEB_CHANGELOG.md` is the concise source parsed by
`/changelog`; keep each web entry to short, simple user-facing bullets and do
not copy the detailed `CHANGELOG.md` wording into the web page. Keep version
titles in both changelogs broad enough to represent all changes in that version,
or at least the major user-facing and operational themes. Diagnostics
page changes, debug tooling, super-admin-only behavior, operator-only
deployment details, and agent-facing notes belong only in `CHANGELOG.md`, never
in `WEB_CHANGELOG.md`.

## Development Process

Read this `AGENTS.md` before making changes.

If a request is unclear, ask questions before implementing.

Give feedback when a requested approach may create security, data integrity,
maintenance, or usability problems.

Do not assume implementation details that affect security, billing, data
retention, Autotask behavior, or workflow semantics without confirming them.

Before finishing implementation work, run relevant tests or explain why tests
could not be run.

Do not commit secrets, generated credentials, local environment files, database
data volumes, raw audio files, or private tunnel tokens.

## Branch And Deployment Workflow

`main` is the production branch. Treat it as the branch that production
instances should pull from after a tested release is ready.

`dev` is the integration and testing branch. It is tracked on GitHub as
`origin/dev` and should receive normal development changes before they are
merged back to `main`. When the user asks for work intended for the dev
instance, make and push that work on `dev` unless they explicitly name another
branch. Do not merge `dev` into `main`, tag a release, or report production
deployment readiness unless the user explicitly asks for that release step.

The dev deployment should run as a separate instance from production, with its
own checkout or worktree, Docker Compose project name, `.env`, database volume,
backup path, host log path, Cloudflare Tunnel token, public hostname, allowed
host setting, WebAuthn origin, and host-facing `NGINX_PUBLIC_PORT`. This keeps
dev testing from sharing production sessions, logs, backups, database state, or
tunnel credentials.

## Agent Orientation Map

Future AI agents should treat this file as the mandatory starting point for the
repository. If a change touches one of the critical areas below, read the linked
agent skill file before editing code:

- Mobile job workflow, review workflow, job statuses, active-job limits, and
  time rounding: `docs/agent-skills/workflow.md`.
- Autotask connectivity, company/ticket lookup, cache behavior, mandatory
  production integration, and submission rules: `docs/agent-skills/autotask.md`.
- Authentication, Cloudflare Access, CSRF, audit events, secret handling, raw
  audio handling, and diagnostic safety: `docs/agent-skills/security.md`.

These files are not optional background reading. They describe the current code
shape and the security/data-integrity boundaries that are easy to break when
adding features quickly.

## Current Application Structure

The application is a FastAPI project under `job_logger/`.

- `job_logger/main.py` creates the FastAPI app, registers routers, applies
  TrustedHost, session, Cloudflare Access, CSP, and security-header middleware.
- `job_logger/version.py` owns the source-controlled application version shown
  in authenticated headers, `/changelog`, and diagnostics. Advance it only
  when requested and keep it aligned with `pyproject.toml`.
- `job_logger/session_timeout.py` clears expired local authenticated sessions
  according to the configured `APP_SESSION_TIMEOUT_HOURS` value and rejects
  managed web-user sessions that were disabled or administratively invalidated.
- `job_logger/config.py` loads every runtime setting from environment variables.
  Production must use `AUTOTASK_PROVIDER=autotask`; Autotask resource IDs are
  stored on managed web users, not in config.
- `job_logger/database.py` owns SQLAlchemy engine/session setup.
- `job_logger/models.py` defines persistent tables for managed web users,
  managed-user session invalidation cutoffs, per-user preferences, jobs, audit
  events, and Autotask submission attempts.
- `job_logger/enums.py` defines workflow, transcription, and ticket-status
  enums used by routes, services, templates, and migrations.
- `job_logger/time_utils.py` centralizes UTC/local conversion and 15-minute
  rounding. Do not duplicate rounding logic elsewhere.
- `job_logger/ui.py` owns shared template context, including the content-derived
  static asset version used to bust browser/PWA caches after CSS or JavaScript
  changes without changing the source-controlled app version.
- `job_logger/services/changelog.py` parses the source-controlled
  `WEB_CHANGELOG.md` into concise plain-text release entries for authenticated
  display.
- `CHANGELOG.md` contains detailed release notes for operators and agents.
  `WEB_CHANGELOG.md` contains short user-facing release notes for `/changelog`.
- `job_logger/routes/auth.py` handles config super-admin login, managed web-user
  login, logout, and local authenticated sessions, including sanitized
  failed-login file logging.
- `job_logger/routes/passkeys.py` handles managed-user passkey registration,
  deletion, and passkey login challenge/verification routes.
- `job_logger/routes/mobile.py` handles `/home`, active job start/end/save,
  active rounded-start adjustment, WebSocket recording streams for active and
  unsubmitted review jobs, compatibility recording uploads, description text
  saves, and Autotask company autocomplete.
- `job_logger/routes/review.py` handles review listing, edit/save/accept/retry,
  updating or deleting existing submitted Autotask entries, ticket lookup for a
  selected job, and explicit local **Delete time entry** cleanup.
- `job_logger/routes/users.py` handles the super-admin managed web-user page,
  including add/edit/enable/disable/delete-as-disable behavior, Autotask
  Resource lookup, per-row Resource metadata refresh, and session invalidation
  when accounts are disabled.
- `job_logger/routes/configuration.py` handles authenticated managed-web-user
  configuration such as immediate light/dark theme selection and explicit
  managed-user password changes.
- `job_logger/routes/changelog.py` handles authenticated `/changelog` release
  history for the discreet version link shown in the shared app header.
- `job_logger/routes/debug.py` handles the super-admin diagnostic page, the
  sanitized successful/failed login windows, app log tail, full backup/restore
  actions, managed web-user session invalidation, and the Autotask API
  connectivity test.
- `job_logger/routes/health.py` exposes private container health endpoints.
- `job_logger/routes/pwa.py` serves the web app manifest and root-scoped
  service worker for installed mobile app behavior. The service worker must not
  cache authenticated job, session, Autotask, or transcription data.
- `job_logger/services/jobs.py` owns core job state transitions and must remain
  the primary place for workflow and job-ownership validation.
- `job_logger/services/autotask.py` owns Autotask providers, connectivity tests,
  company/ticket lookup, per-user resource service-call lookup, cache behavior,
  pagination, submission-time status mapping, time entry submission,
  existing-entry updates, and existing-entry deletes.
- `job_logger/services/users.py` owns managed web-user validation, optional
  Autotask Resource email storage, password hashing and changes, first-user
  legacy job claiming, and delete-as-disable rules.
- `job_logger/services/session_control.py` owns server-side managed web-user
  session invalidation cutoffs used by diagnostics and user disable actions.
- `job_logger/services/preferences.py` owns per-authenticated-user
  configuration validation and persistence.
- `job_logger/services/passkeys.py` owns WebAuthn relying-party/origin
  resolution, challenge generation, passkey verification, public credential
  storage, credential counters, and safe passkey deletion.
- `job_logger/services/ai_cleanup.py` owns server-side Gemini, Groq, Ollama,
  and LM Studio summary cleanup, including request construction,
  provider-specific instruction placement, private-network provider URL
  validation, safe response parsing, and provider error normalization.
- `job_logger/services/transcription.py` owns speech-to-text provider behavior.
- `job_logger/services/audit.py` records immutable audit events.
- `job_logger/services/backups.py` creates and restores portable gzip JSON full
  database backups, writes hourly automatic backup files, and enforces automatic
  backup retention.
- `job_logger/services/login_failures.py` writes and reads the host-mounted
  sanitized successful/failed login JSONL logs in `LOG_DIR`, defaulting to
  `job-logger-login-successes.log` and `job-logger-login-failures.log` inside
  Docker's `/data/logs` mount.
- `job_logger/templates/` contains Jinja pages for mobile, review, users,
  config, changelog, debug, and authentication views.
- `job_logger/static/` contains browser-side JavaScript, CSS, PWA metadata, and
  source-controlled app icons.
- `migrations/versions/` contains Alembic schema migrations.
- `scripts/` contains operational helper scripts, including Autotask ID
  discovery.
- `tests/` contains workflow, diagnostics, provider, and security regression
  tests.

## Current High-Level Flow

The normal workflow is:

1. User authenticates through Cloudflare Access when enabled, then through the
   app login.
2. The config super admin opens `/users` to create and edit managed web users.
   The page lists users in a desktop table and mobile card layout with icon-only
   row actions for refresh, edit, enable/disable, and delete-as-disable.
   The add form suggests a username from the full name, and add/edit forms can
   query Autotask Resources to select the matching resource ID and capture the
   returned email address. Per-row refresh re-queries Autotask Resources and
   updates stored local name/email metadata only for the saved resource ID.
   Delete actions always disable the selected account, sign out its existing
   sessions on the next request, and preserve the row so future login attempts
   can show the disabled-account message. The first managed web user claims any
   existing unowned jobs from earlier single-user installs.
3. A managed web user may open `/config` to choose dark or light theme for
   their own login, enable the default-off **Submit from Work in Progress**
   option, change their password, and add or delete passkeys. Config changes
   save and apply immediately without a visible save action, except password
   and passkey actions which are explicit. The password card shows password
   requirements. The config super admin has no `/config` access and stays dark.
4. A managed web user opens `/home`.
5. The `/home` page renders from local application state without running an
   Autotask API contactability check. After the page has loaded, browser
   JavaScript queries `/home/service-calls` to populate service-call start
   cards for the selected local date and that user's Autotask resource,
   including each call's local start/end time range. The mobile date navigator
   can move backward/forward by day or open a calendar picker, but service-call
   starts are still verified server-side for the submitted date and resource.
6. User starts Job 1 or Job 2. Blank Start Work creates a local active job
   owned by that web user without first probing Autotask. At most two active
   jobs may exist at once per web user.
7. After the job starts, the user enters/selects an Autotask company by client
   name. Manual client text is allowed, but selected company IDs are preferred
   for exact ticket lookup.
8. User chooses an open Autotask ticket from the active-job ticket panel. If no
   tickets are loaded yet, the whole panel is the load control and shows a
   spinner while Autotask data is being queried. Ticket options show detected
   Remote/On-Site/Not specified labels from ticket title and description text,
   falling back to remote-only Autotask ticket sources such as `RMM Alert`,
   `Datto Alert`, `BCDR Alert`, and `Email Alert` when text detection has no
   result. Remote and On-Site color treatment matches service-call cards.
   Mobile ticket numbers are populated from that selection instead of manual
   entry. Selection never patches Autotask ticket status; it stores verified
   local ticket metadata and defaults the editable local ticket status to
   In progress until the job's time entry is submitted. The selected ticket
   status is shown and editable on Work in Progress. Read-only ticket
   descriptions stay in short scrollable boxes on Work in Progress and review
   detail.
9. User chooses whether the work is Remote or On-Site. The mode is stored on
   the job and appears as the leading prefix in the review summary textarea so
   it can be corrected before Autotask submission.
10. User records notes during an active job from the Summary notes action row,
   where **Record** sits beside the optional **AI Cleanup** action. Review
   detail uses the same paired summary action row for unsubmitted jobs. The record
   button becomes a stop button while audio chunks stream to the server over
   WebSocket. Recording, sending, and converting progress use plain status
   text, and stopping capture keeps the disabled record button in a loading
   state until the final transcript returns.
11. When enabled, user can click **AI Cleanup** to send the current summary text
   through the configured server-side cleanup provider. On
   mobile, progress and failure details use the same plain-text status line as
   audio recording, while the **AI Cleanup** button itself shows the spinner
   during cleanup. The returned text replaces the summary textarea and remains
   subject to normal save/review behavior.
12. User can save active job edits before ending work.
13. User ends work with a mandatory client name. With the default workflow, the
    active-card **End Work** action shares a row with the destructive **Delete**
    action, and the job moves to review. If **Submit from Work in Progress** is
    enabled, the end-work action submits to Autotask immediately after
    validating ticket number, ticket status, rounded end time, client, and
    summary notes. Missing local submission fields leave the job active so the
    user can fix them; Autotask provider failures move the job to the
    failed-submission review state with the safe error message.
14. User reviews the job from `/review`, edits time/status/notes if needed,
    optionally records more audio notes before Autotask submission, and keeps
    the selected client/ticket identity read-only. Review detail groups action
    controls into compact rows with at most two buttons per row; submitted
    entries pair **Edit Entry** with **Delete From Autotask**, while local
    unsubmitted entries pair the submit action with **Delete time entry** when
    possible. Active jobs selected in Review show **End Work** paired with
    **Delete time entry** and post to the normal end-work route. Directly
    submitted jobs still appear in Review for submitted-entry
    **Edit Entry** and **Delete From Autotask** actions. Active jobs opened in
    Review show the same rounded stop preview as Work in Progress, but review
    saves must not apply that displayed end time until the job is actually
    ended.
15. Accept/retry submits a reviewed job to Autotask idempotently with the
    owning managed web user's resource ID.
16. Successfully submitted jobs can use **Edit Entry** for date/time/status/notes
    updates against the existing Autotask time entry, or **Delete From Autotask**
    to remove the external time entry and return the local job to review.
    `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=true` allows **Edit Entry** to
    reopen previously Complete tickets to In progress before patching
    `TimeEntries`, then apply the selected final status after the time-entry
    patch when needed. With the default disabled setting, submitted-entry edits
    patch only `TimeEntries`.
    Ticket/client identity, local delete, accept/resend, and retry stay blocked
    while the job remains submitted.
17. Submission attempts and important state changes are recorded for audit and
    diagnostics.
18. Managed users without a passkey see a Home prompt to add one once after a
    successful login. `/config` always shows passkey management. Later passkey
    login uses `/login/passkey/options` and `/login/passkey/verify`; failed or
    canceled passkey login must leave the normal password form available.
19. Authenticated users may open `/changelog` from the discreet header version
    link to view the current source-controlled version and prior concise release
    notes parsed from `WEB_CHANGELOG.md`. The current-version panel must show
    that version's simple change list, not only the release title.

## Current Autotask Dependency

Autotask is not an optional production dependency anymore. The app depends on
Autotask Companies and Tickets to help select the correct ticket before work is
submitted.

In production:

- `APP_ENV=production` requires `AUTOTASK_PROVIDER=autotask`.
- `APP_USERNAME`/`APP_PASSWORD` authenticate the config super admin only.
- Each managed web user must be created on `/users` with an Autotask resource
  ID before that person can start work.
- `/home` and blank Start Work do not run Autotask contactability probes.
- Service-call loading, company lookup, ticket lookup, and Autotask submission
  still call Autotask only when those specific workflows need provider data.
  Service-call and open-ticket selection are read/query-only against Autotask
  and must not patch remote ticket status before time-entry submission.
- Ticket status writes are disabled by default. Set
  `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=true` only when the Autotask API user
  is allowed to patch `Tickets.status` and the deployment intentionally wants
  Job Logger to advance or close tickets as part of submission/edit workflows.
- Super-admin resource lookup on `/users` calls Autotask Resources only through
  the server-side provider; browser code never contacts Autotask directly.
  Returned resource email metadata is optional and is stored only when a user
  selects a resource that includes one. Per-row refresh uses the same provider
  and updates only safe local metadata after matching the saved resource ID.
- The `/debug` page provides the supported manual **Test Autotask API** action.
- The `/debug` page provides a super-admin-only **Log out web users** action
  that invalidates all managed web-user sessions without ending the current
  super-admin session.
- Mock Autotask mode is only for tests and isolated development.

## Documentation Maintenance Rules For Agents

When changing workflow, Autotask behavior, security behavior, Docker/runtime
configuration, database schema, or diagnostics:

- Update this file if the top-level structure or required reading changes.
- Update the relevant file in `docs/agent-skills/`.
- Update `README.md` when operators need to know about behavior or deployment
  changes.
- Update `CHANGELOG.md` for every user-visible, security, workflow, database,
  Docker, Autotask, transcription, or diagnostic change.
- Update `WEB_CHANGELOG.md` for every released version with short web-facing
  bullets that are simpler than the detailed `CHANGELOG.md` entry. Exclude
  diagnostics, debug-page, super-admin-only, operator-only, and agent-facing
  changes from `WEB_CHANGELOG.md`.
