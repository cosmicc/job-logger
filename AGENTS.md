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
refresh, edit, enable/disable, and delete/delete-as-disable. The refresh action
re-queries Autotask Resources, requires the returned resource ID to match the
stored ID, and updates only safe local name/email metadata. The add form may
suggest usernames from full names, such as `jblow` for `Joe Blow`, and add/edit
forms may query Autotask Resources for a super-admin-only resource picker.
Store only salted password verifiers, never raw managed user passwords.
Managed-user passwords must be at least 8 characters and include lowercase,
uppercase, number, and symbol characters.
Disabled web users must be blocked from new logins and from using old signed
sessions. Deleting a web user with job history must preserve history by
disabling the account instead of removing the row.

Managed web users may change per-login configuration on `/config`. Per-user
configuration is database-backed, defaults to the dark theme, saves immediately
when an option changes, and currently supports `dark` or `light` visual themes
for all authenticated mobile and web pages. The password-change section on
`/config` is the exception: it requires two matching password entries and an
explicit **Change password** submit button. The config super admin does not have
user settings, does not see the Config menu item, cannot access `/config`, and
always renders in dark mode.

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
or other sensitive values. Failed app-login attempts may be written to the
host-mounted JSONL login-failure log and shown on `/debug`, but only with
sanitized metadata such as timestamp, client IP, submitted username, user agent,
request/proxy details, and password-present/length. Never write or display the
raw submitted password.

Prefer secure defaults. Cookies must be HTTP-only, secure when served over HTTPS,
and SameSite-protected. Forms and state-changing requests must use CSRF
protection.

The application must maintain immutable audit events for important actions,
including job start, job end, description recording, transcription updates,
manual edits, review decisions, Autotask submission attempts, Autotask submission
success, Autotask submission failure, and authentication-sensitive events.

Raw audio must not be stored by default. If audio retention is ever added, it
must be explicit, configurable, documented, access-controlled, and auditable.

AI summary cleanup sends job summary text to the configured provider only when
`AI_CLEANUP_ENABLED=true` and `AI_CLEANUP_PROVIDER` is `gemini`, `grok`,
`ollama`, or `lm_studio`. Treat summary text as customer/work data. The server
must validate authentication and CSRF, bound input length, keep API keys, local
provider URLs, and cleanup instructions server-side in Docker or environment
variables, set `store=false` on Gemini requests, constrain Ollama and LM Studio
cleanup URLs to server-local hosts, and audit only metadata such as provider,
model, source, and text lengths. Do not store raw cleanup prompts or full
cleaned/uncleaned summaries in audit details.

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
4. The job becomes available for that user to review. The config super admin
   may view all jobs but cannot mutate them.
5. The review page allows time, status, and notes to be edited before
   acceptance while keeping the selected Autotask client and ticket read-only.
6. An accepted job creates an Autotask time entry using the owning user's
   Autotask resource ID.
7. A successfully submitted Autotask job keeps ticket and client identity
   read-only. Its job date, start time, end time, summary notes, and ticket
   status can be changed only through the audited **Edit Entry** action, which
   updates the existing Autotask time entry instead of creating another entry.
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

Autotask time entries are created only after a job is reviewed and accepted.

The required Autotask time-entry fields for this application are:

- Ticket number.
- Summary notes.
- Ticket status.
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
`TimeEntries.resourceID` on create. Static Autotask role and billing-code IDs
must not be configured. The live provider must query the selected ticket at
submission time, use `Tickets.assignedResourceroleID` as `TimeEntries.roleID`,
and omit `TimeEntries.billingCodeID` so Autotask inherits the selected ticket's
Work Type on create. API credentials, ticket status IDs, time-entry type, and
optional `AUTOTASK_IMPERSONATION_RESOURCE_ID` remain environment configuration.
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
**Record Audio** button while the recording is still being sent or converted
and the **AI Cleanup** button while cleanup is running.

The local faster-whisper provider may use `FASTER_WHISPER_INITIAL_PROMPT` to
guide transcript formatting, including rendering dictated punctuation words as
punctuation marks. Treat it as a best-effort model hint, not a validation or
security control.

AI summary cleanup is separate from speech-to-text. It sends the current
editable summary text to the configured server-side cleanup provider and
replaces the summary textarea with the returned cleaned text. It must not
submit to Autotask or bypass review.

The review page must allow the transcribed description to be edited or
re-recorded before the job is accepted and submitted to Autotask.

Do not permanently store raw audio by default.

## Web Interface Requirements

The mobile interface must be optimized for quick use from a phone.

Managed web-user pages must respect the current user's saved theme preference.
The default is the dark theme. Light theme support must cover mobile, review,
user management, config, debug, and login surfaces through shared CSS variables
instead of a separate unaudited template branch. Super-admin pages always use
dark mode.

On phone-sized `/mobile` layouts, the authenticated top bar uses an X close
control instead of the logout action so an installed mobile web app can be
dismissed without ending the local server-side session. Full-width `/mobile`,
review, debug, and other non-mobile authenticated views still expose the
explicit logout control.

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
- `job_logger/config.py` loads every runtime setting from environment variables.
  Production must use `AUTOTASK_PROVIDER=autotask`; Autotask resource IDs are
  stored on managed web users, not in config.
- `job_logger/database.py` owns SQLAlchemy engine/session setup.
- `job_logger/models.py` defines persistent tables for managed web users,
  per-user preferences, jobs, audit events, and Autotask submission attempts.
- `job_logger/enums.py` defines workflow, transcription, and ticket-status
  enums used by routes, services, templates, and migrations.
- `job_logger/time_utils.py` centralizes UTC/local conversion and 15-minute
  rounding. Do not duplicate rounding logic elsewhere.
- `job_logger/ui.py` owns shared template context, including the content-derived
  static asset version used to bust browser/PWA caches after CSS or JavaScript
  changes without changing the source-controlled app version.
- `job_logger/services/changelog.py` parses the source-controlled
  `CHANGELOG.md` into plain-text release entries for authenticated display.
- `job_logger/routes/auth.py` handles config super-admin login, managed web-user
  login, logout, and local authenticated sessions, including sanitized
  failed-login file logging.
- `job_logger/routes/mobile.py` handles `/mobile`, active job start/end/save,
  active rounded-start adjustment, WebSocket recording streams for active and
  unsubmitted review jobs, compatibility recording uploads, description text
  saves, and Autotask company autocomplete.
- `job_logger/routes/review.py` handles review listing, edit/save/accept/retry,
  updating or deleting existing submitted Autotask entries, ticket lookup for a
  selected job, and explicit local **Delete time entry** cleanup.
- `job_logger/routes/users.py` handles the super-admin managed web-user page,
  including add/edit/enable/disable/delete-or-disable behavior, Autotask
  Resource lookup, and per-row Resource metadata refresh.
- `job_logger/routes/configuration.py` handles authenticated managed-web-user
  configuration such as immediate light/dark theme selection and explicit
  managed-user password changes.
- `job_logger/routes/changelog.py` handles authenticated `/changelog` release
  history for the discreet version link shown in the shared app header.
- `job_logger/routes/debug.py` handles the super-admin diagnostic page, the
  sanitized failed-login window, full backup/restore actions, and the Autotask
  API connectivity test.
- `job_logger/routes/health.py` exposes private container health endpoints.
- `job_logger/routes/pwa.py` serves the web app manifest and root-scoped
  service worker for installed mobile app behavior. The service worker must not
  cache authenticated job, session, Autotask, or transcription data.
- `job_logger/services/jobs.py` owns core job state transitions and must remain
  the primary place for workflow and job-ownership validation.
- `job_logger/services/autotask.py` owns Autotask providers, connectivity tests,
  company/ticket lookup, per-user resource service-call lookup, cache behavior,
  pagination, status mapping, time entry submission, existing-entry updates, and
  existing-entry deletes.
- `job_logger/services/users.py` owns managed web-user validation, optional
  Autotask Resource email storage, password hashing and changes, first-user
  legacy job claiming, and delete-or-disable rules.
- `job_logger/services/preferences.py` owns per-authenticated-user
  configuration validation and persistence.
- `job_logger/services/ai_cleanup.py` owns server-side Gemini, Groq, Ollama,
  and LM Studio summary cleanup, including request construction, local-provider
  URL validation, safe response parsing, and provider error normalization.
- `job_logger/services/transcription.py` owns speech-to-text provider behavior.
- `job_logger/services/audit.py` records immutable audit events.
- `job_logger/services/backups.py` creates and restores portable gzip JSON full
  database backups for authenticated diagnostics.
- `job_logger/services/login_failures.py` writes and reads the host-mounted
  sanitized failed-login JSONL log in `LOG_DIR`, defaulting to
  `job-logger-login-failures.log` inside Docker's `/data/logs` mount.
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
   row actions for refresh, edit, enable/disable, and delete/delete-as-disable.
   The add form suggests a username from the full name, and add/edit forms can
   query Autotask Resources to select the matching resource ID and capture the
   returned email address. Per-row refresh re-queries Autotask Resources and
   updates stored local name/email metadata only for the saved resource ID. The
   first managed web user claims any existing unowned jobs from earlier
   single-user installs.
3. A managed web user may open `/config` to choose dark or light theme for
   their own login. Config changes save and apply immediately without a visible
   save action. The same page allows an explicit two-entry login password
   change. The config super admin has no `/config` access and stays dark.
4. A managed web user opens `/mobile`.
5. The `/mobile` page renders from local application state without running an
   Autotask API contactability check. After the page has loaded, browser
   JavaScript queries `/mobile/service-calls` to populate service-call start
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
   spinner while Autotask data is being queried. Mobile ticket numbers are
   populated from that selection instead of manual entry. Read-only ticket
   descriptions stay in short scrollable boxes on Work in Progress and review
   detail.
9. User chooses whether the work is Remote or On-Site. The mode is stored on
   the job and appears as the leading prefix in the review summary textarea so
   it can be corrected before Autotask submission.
10. User records notes during an active job from the Summary notes area above
   the optional AI Cleanup action. The record button becomes a stop button
   while audio chunks stream to the server over WebSocket. Recording, sending,
   and converting progress use plain status text, and stopping capture keeps
   the disabled record button in a loading state until the final transcript
   returns.
11. When enabled, user can click **AI Cleanup** to send the current summary text
   through the configured server-side cleanup provider. On
   mobile, progress and failure details use the same plain-text status line as
   audio recording, while the **AI Cleanup** button itself shows the spinner
   during cleanup. The returned text replaces the summary textarea and remains
   subject to normal save/review behavior.
12. User can save active job edits before ending work.
13. User ends work with a mandatory client name. The job moves to review.
14. User reviews the job from `/review`, edits time/status/notes if needed,
    optionally records more audio notes before Autotask submission, and keeps
    the selected client/ticket identity read-only.
15. Accept/retry submits a reviewed job to Autotask idempotently with the
    owning managed web user's resource ID.
16. Successfully submitted jobs can use **Edit Entry** for date/time/status/notes
    updates against the existing Autotask time entry, or **Delete From Autotask**
    to remove the external time entry and return the local job to review.
    Ticket/client identity, local delete, accept/resend, and retry stay blocked
    while the job remains submitted.
17. Submission attempts and important state changes are recorded for audit and
    diagnostics.
18. Authenticated users may open `/changelog` from the discreet header version
    link to view the current source-controlled version and prior release notes
    parsed from `CHANGELOG.md`.

## Current Autotask Dependency

Autotask is not an optional production dependency anymore. The app depends on
Autotask Companies and Tickets to help select the correct ticket before work is
submitted.

In production:

- `APP_ENV=production` requires `AUTOTASK_PROVIDER=autotask`.
- `APP_USERNAME`/`APP_PASSWORD` authenticate the config super admin only.
- Each managed web user must be created on `/users` with an Autotask resource
  ID before that person can start work.
- `/mobile` and blank Start Work do not run Autotask contactability probes.
- Service-call loading, company lookup, ticket lookup, and Autotask submission
  still call Autotask only when those specific workflows need provider data.
- Super-admin resource lookup on `/users` calls Autotask Resources only through
  the server-side provider; browser code never contacts Autotask directly.
  Returned resource email metadata is optional and is stored only when a user
  selects a resource that includes one. Per-row refresh uses the same provider
  and updates only safe local metadata after matching the saved resource ID.
- The `/debug` page provides the supported manual **Test Autotask API** action.
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
