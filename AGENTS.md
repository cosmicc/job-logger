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
or other sensitive values.

Prefer secure defaults. Cookies must be HTTP-only, secure when served over HTTPS,
and SameSite-protected. Forms and state-changing requests must use CSRF
protection.

The application must maintain immutable audit events for important actions,
including job start, job end, description recording, transcription updates,
manual edits, review decisions, Autotask submission attempts, Autotask submission
success, Autotask submission failure, and authentication-sensitive events.

Raw audio must not be stored by default. If audio retention is ever added, it
must be explicit, configurable, documented, access-controlled, and auditable.

AI summary cleanup sends job summary text to the configured external provider
only when `AI_CLEANUP_ENABLED=true`, `AI_CLEANUP_PROVIDER` is `gemini` or
`grok`, and the matching provider API key is configured. Treat summary text as
customer/work data. The server must validate authentication and CSRF, bound
input length, keep API keys and cleanup instructions server-side in Docker or
environment variables, set `store=false` on Gemini requests, and audit only
metadata such as provider, model, source, and text lengths. Do not store raw
cleanup prompts or full cleaned/uncleaned summaries in audit details.

## Core Workflow

The mobile web page must provide a quick active-job workflow with these actions:

- Start work.
- End work.
- Record description.

Description recording is only available during an active job.

Recorded jobs follow this lifecycle:

1. A draft job is created when work starts.
2. The active job is ended by the user.
3. The job becomes available for review.
4. The review page allows time, status, and notes to be edited before
   acceptance while keeping the selected Autotask client and ticket read-only.
5. An accepted job creates an Autotask time entry.
6. A successfully submitted Autotask job keeps ticket and client identity
   read-only. Its job date, start time, end time, summary notes, and ticket
   status can be changed only through the audited **Edit Entry** action, which
   updates the existing Autotask time entry instead of creating another entry.
   The audited **Delete From Autotask** action may delete the external time
   entry and move the local job back to review, but must not delete the local
   job record.
7. Rejected, failed, or edited jobs remain available for audit history.

Jobs must never disappear silently. Destructive deletion should be avoided.
Prefer archived, rejected, superseded, or voided states with audit records.

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

Autotask API errors must be recorded clearly for review and troubleshooting
without exposing credentials or sensitive protocol details.

## Speech-to-Text Requirements

Speech-to-text transcription must be configurable by provider.

The application should define a provider interface so transcription backends can
be changed without rewriting the job workflow.

The translated speech-to-text description must populate the editable job
description used on the review page.

After the user stops mobile recording, the browser status must distinguish the
upload and transcription phases: first **Sending data to server...**, then
**Converting audio to text...**, then **Conversion complete.** when the final
transcript has been returned and pasted into the summary field.

The local faster-whisper provider may use `FASTER_WHISPER_INITIAL_PROMPT` to
guide transcript formatting, including rendering dictated punctuation words as
punctuation marks. Treat it as a best-effort model hint, not a validation or
security control.

AI summary cleanup is separate from speech-to-text. It sends the current
editable summary text to the server-side Gemini or Groq cleanup provider and
replaces the summary textarea with the returned cleaned text. It must not
submit to Autotask or bypass review.

The review page must allow the transcribed description to be edited before the
job is accepted and submitted to Autotask.

Do not permanently store raw audio by default.

## Web Interface Requirements

The mobile interface must be optimized for quick use from a phone.

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
idempotency, transcription status, and immutable audit history.

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
  on authenticated diagnostics and must only be advanced when requested.
- `job_logger/config.py` loads every runtime setting from environment variables.
  Production must use `AUTOTASK_PROVIDER=autotask`.
- `job_logger/database.py` owns SQLAlchemy engine/session setup.
- `job_logger/models.py` defines persistent tables for jobs, audit events, and
  Autotask submission attempts.
- `job_logger/enums.py` defines workflow, transcription, and ticket-status
  enums used by routes, services, templates, and migrations.
- `job_logger/time_utils.py` centralizes UTC/local conversion and 15-minute
  rounding. Do not duplicate rounding logic elsewhere.
- `job_logger/routes/auth.py` handles login/logout and local authenticated
  sessions.
- `job_logger/routes/mobile.py` handles `/mobile`, active job start/end/save,
  active rounded-start adjustment, WebSocket recording streams, compatibility
  recording uploads, description text saves, and Autotask company autocomplete.
- `job_logger/routes/review.py` handles review listing, edit/save/accept/retry,
  updating or deleting existing submitted Autotask entries, ticket lookup for a
  selected job, rejection, and force purge behavior.
- `job_logger/routes/debug.py` handles the authenticated diagnostic page and the
  Autotask API connectivity test.
- `job_logger/routes/health.py` exposes container health endpoints.
- `job_logger/routes/pwa.py` serves the web app manifest and root-scoped
  service worker for installed mobile app behavior. The service worker must not
  cache authenticated job, session, Autotask, or transcription data.
- `job_logger/services/jobs.py` owns core job state transitions and must remain
  the primary place for workflow validation.
- `job_logger/services/autotask.py` owns Autotask providers, connectivity tests,
  company/ticket lookup, cache behavior, pagination, status mapping, time entry
  submission, existing-entry updates, and existing-entry deletes.
- `job_logger/services/ai_cleanup.py` owns server-side Gemini and Groq summary
  cleanup, including request construction, safe response parsing, and provider
  error normalization.
- `job_logger/services/transcription.py` owns speech-to-text provider behavior.
- `job_logger/services/audit.py` records immutable audit events.
- `job_logger/templates/` contains Jinja pages for mobile, review, debug, and
  authentication views.
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
2. User opens `/mobile`.
3. The `/mobile` page renders from local application state without running an
   Autotask API contactability check. After the page has loaded, browser
   JavaScript queries `/mobile/service-calls` to populate today's service-call
   start cards.
4. User starts Job 1 or Job 2. Blank Start Work creates a local active job
   without first probing Autotask. At most two active jobs may exist at once.
5. After the job starts, the user enters/selects an Autotask company by client
   name. Manual client text is allowed, but selected company IDs are preferred
   for exact ticket lookup.
6. User chooses an open Autotask ticket from the active-job ticket panel. If no
   tickets are loaded yet, the whole panel is the load control and shows a
   spinner while Autotask data is being queried. Mobile ticket numbers are
   populated from that selection instead of manual entry.
7. User chooses whether the work is Remote or On-Site. The mode is stored on
   the job and appears as the leading prefix in the review summary textarea so
   it can be corrected before Autotask submission.
8. User records notes during an active job. The record button becomes a stop
   button while audio chunks stream to the server over WebSocket, and stopping
   capture shows sending/converting/completed progress until the final
   transcript returns.
9. When enabled, user can click **AI Cleanup** to send the current summary text
   through the configured server-side Gemini or Groq cleanup provider. The
   returned text replaces the summary textarea and remains subject to normal
   save/review behavior.
10. User can save active job edits before ending work.
11. User ends work with a mandatory client name. The job moves to review.
12. User reviews the job from `/review`, edits time/status/notes if needed, and
    keeps the selected client/ticket identity read-only.
13. Accept/retry submits a reviewed job to Autotask idempotently.
14. Successfully submitted jobs can use **Edit Entry** for date/time/status/notes
    updates against the existing Autotask time entry, or **Delete From Autotask**
    to remove the external time entry and return the local job to review.
    Ticket/client identity, reject, purge, accept/resend, and retry stay blocked
    while the job remains submitted.
15. Submission attempts and important state changes are recorded for audit and
    diagnostics.

## Current Autotask Dependency

Autotask is not an optional production dependency anymore. The app depends on
Autotask Companies and Tickets to help select the correct ticket before work is
submitted.

In production:

- `APP_ENV=production` requires `AUTOTASK_PROVIDER=autotask`.
- `/mobile` and blank Start Work do not run Autotask contactability probes.
- Service-call loading, company lookup, ticket lookup, and Autotask submission
  still call Autotask only when those specific workflows need provider data.
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
