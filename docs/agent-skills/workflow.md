# Job Logger Agent Skill: Workflow

Read this file before changing mobile work entry, active job behavior, review
behavior, job statuses, time rounding, or job-related database fields.

## Core Service Boundary

`job_logger/services/jobs.py` is the workflow authority. Routes should collect
and validate request-level concerns such as authentication and CSRF, then call
service functions for state changes. Do not reimplement job status rules inside
templates, JavaScript, or route handlers.

Important workflow service responsibilities include:

- Starting active jobs.
- Enforcing the maximum of two simultaneous active jobs.
- Assigning Job 1 and Job 2 slots.
- Updating active ticket/client/summary fields.
- Adjusting rounded active start time in 15-minute increments.
- Ending active jobs and moving them to review.
- Deleting an active in-progress job when the user explicitly discards it.
- Validating review fields.
- Applying review edits.
- Accepting/retrying Autotask submission.
- Preventing active jobs from being force-purged.

## Active Job Flow

The mobile page is `/mobile`, implemented by `job_logger/routes/mobile.py` and
`job_logger/templates/mobile.html`.

New work starts through `POST /jobs/start`.

Security and data-integrity requirements for start:

- The user must be authenticated.
- CSRF must be valid.
- The server must enforce the mandatory Autotask connectivity gate before
  creating the job. This can use the short start-work connectivity cache so
  repeated Start Work taps do not run a live Autotask probe every time.
- If the live or cached Autotask result is unavailable, no job may be created
  and an audit event must be recorded.
- New mobile jobs intentionally start without client, company, or ticket values.
  The route ignores stale or crafted pre-start client/ticket fields so those
  values can only be attached through the active-job workflow.
- The service layer must enforce the two-active-job limit.

Active jobs support these updates before completion:

- Ticket number populated by selecting an Autotask open-ticket option.
- Selected ticket title from Autotask open-ticket lookup.
- Selected ticket description from Autotask open-ticket lookup, displayed as
  read-only context after a ticket is chosen.
- Client name.
- Selected Autotask company ID while the active job has not already locked an
  Autotask company.
- Summary notes.
- Work location mode, either Remote or On-Site, which is stored separately from
  the visible notes.
- Rounded start time through server-validated mobile `-15` and `+15` minute
  buttons on either side of the displayed time.

The active job save route is `POST /jobs/{job_id}/ticket-number`. The name is
historical; it now saves active-job client and summary edits, not ticket
selection from the open-ticket picker.

The mobile active-job ticket number is not a manual text entry. The open-ticket
picker posts the clicked ticket number to `POST /jobs/{job_id}/ticket`. That
route uses the recently loaded server-side open-ticket selection cache when it
is still fresh, falls back to a live Autotask lookup when needed, verifies the
submitted ticket belongs to that safe list, stores the ticket number, title,
and bounded ticket description, and records an audit event. When an active job
has no ticket number, the mobile page shows the open-ticket panel under the
client field. The **Find tickets** button saves the current active client fields
before querying Autotask, and a job that already has a saved client auto-loads
the picker. After selection, the browser should immediately hide the open-ticket
panel and show the selected ticket number, ticket title, and ticket description
in Work in Progress without waiting for a page reload.

The work-location switch is intentionally not written into `summary_notes` or
the mobile textarea. Store the mode on the job and let Autotask submission
prefix `summaryNotes` with `Remote` or `On-Site` only when creating the time
entry.

The active mobile card should expose only one client entry point for each job.
After an Autotask company is selected, the active job displays that client as a
read-only value and submits hidden copies only for normal form flow. The
service layer still enforces the lock because hidden fields are not security
controls.

Active jobs can be discarded through `POST /jobs/{job_id}/delete`. This route
is only for in-progress jobs, requires authentication and CSRF, deletes the
local active job, and records `job.active.deleted` with sanitized details. Do
not use this endpoint for reviewed, submitted, or failed jobs.

## Ending Work

Work ends through `POST /jobs/{job_id}/end`.

Ending work requires:

- Authenticated user.
- Valid CSRF token.
- Existing active job.
- Mandatory client name.
- Valid selected company ID if one is submitted.
- Current summary notes carried from the mobile textarea.

After ending, the job moves to review. Do not submit time to Autotask directly
from mobile end-work. Submission happens only after review acceptance or retry.

## Speech-To-Text Flow

Mobile recording is browser-side in `job_logger/static/mobile.js`.

Current behavior:

- Record Audio starts audio capture.
- The button changes to **Stop recording** and turns red while browser recording
  is active.
- The browser opens `WebSocket /jobs/{job_id}/description/audio/stream`,
  sends CSRF-protected stream metadata first, then streams `MediaRecorder`
  audio chunks as binary WebSocket messages.
- The server starts an interim transcription attempt as soon as the first chunk
  arrives. The current faster-whisper provider is batch-oriented, so interim
  text is best-effort from the buffered media snapshot.
- Clicking **Stop recording** ends browser capture, lets `MediaRecorder` flush its
  final chunk, sends WebSocket `finish`, and keeps the control disabled while
  the status line shows transcode/transcription progress until the final
  transcript or a bounded error response returns. The legacy
  `POST /jobs/{job_id}/description/audio` endpoint remains as a compatibility
  upload path, but the mobile UI should use the WebSocket stream.
- Raw audio is not permanently stored by default.
- Transcription text updates the same summary field that review and Autotask
  submission use.

Manual summary notes typed in the textarea must be preserved when active job
changes are saved or work is ended.

## Review Flow

The review page is `/review`, implemented by `job_logger/routes/review.py`,
`job_logger/templates/review.html`, and `job_logger/static/review.js`.

Review supports:

- Selecting jobs from the review list.
- Viewing the selected ticket number and client name as read-only Autotask
  identity fields.
- Editing ticket status, start date/time, end date/time, and summary notes.
- Saving edits without a ticket number.
- Saving active jobs without an end date/time.
- Accepting or retrying submission only when the ticket number and required
  submission fields are present.
- Looking up open Autotask tickets for the stored selected company ID or client
  name.

Ticket number is intentionally required only before Autotask submission, not for
ordinary save operations.

Review ticket selection persists through `POST /review/{job_id}/ticket`. The
route uses the recently loaded server-side open-ticket selection cache when it
is still fresh, falls back to a live Autotask lookup when needed, verifies the
submitted ticket number belongs to that safe list, stores the ticket number,
title, and bounded ticket description, and records an audit event. Do not trust
browser-supplied ticket title, ticket description, ticket number, client name,
or company ID values on review save/accept; the route must overlay those fields
from the stored job before validation.

When a ticket is selected from Autotask lookup, store the ticket title with the
job and use it as the selected-job detail heading. If no ticket has been
selected, the detail heading should read `Unassigned Ticket`. Older jobs that
have a ticket number but no stored title may display the ticket number as a
fallback. Once a job has a ticket number, hide the open-ticket lookup panel for
that job. Review ticket selection should update the read-only ticket number,
selected-job heading, and read-only ticket description card in place after the
server verifies and stores the ticket.

## Job Status Expectations

Jobs must never disappear silently. Prefer explicit workflow states, archived
states, rejected states, failed submission states, or audited purge paths.

Force purge exists for strict cleanup from review detail, but active jobs cannot
be purged from that endpoint. Active jobs have the separate audited delete route
described above. Be careful before expanding destructive behavior.

## Time Rules

All user-facing dates and times use `America/Detroit`.

All user-facing times display in 12-hour `am`/`pm` format. Keep any 24-hour
values limited to internal compatibility parsing or external API payloads.

All stored timestamps are UTC.

Use `job_logger/time_utils.py` for:

- Local/UTC conversion.
- 15-minute rounding.
- Autotask date/time formatting.
- Duration calculations.

Do not duplicate time rounding in routes, templates, JavaScript, or Autotask
submission code. JavaScript controls may adjust visible form values, but the
server remains authoritative.

## Tests To Consider

When changing workflow behavior, relevant tests usually live in:

- `tests/test_workflow.py`.
- `tests/test_security.py`.
- `tests/test_autotask_cache.py` when lookup behavior is involved.
- `tests/test_debug.py` when diagnostics or connectivity checks are involved.
