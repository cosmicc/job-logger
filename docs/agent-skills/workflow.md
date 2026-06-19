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

The `/mobile` top bar includes both the normal logout form and an X close button
wired by `job_logger/static/pwa.js`. CSS decides which action is visible:
full-width web layouts show logout, while phone-sized mobile layouts show the X.
The close button should only attempt to close the installed web app or browser
tab; it must not clear the authenticated local session, submit logout, or
perform another state-changing action. Keep the explicit logout form available
on non-mobile authenticated pages.

New blank work starts through `POST /jobs/start`. A user can also start work
from a current-day Autotask service call through
`POST /jobs/start/service-call`.

Security and data-integrity requirements for start:

- The user must be authenticated.
- CSRF must be valid.
- The server must enforce the mandatory Autotask connectivity gate before
  creating the job. This can use the short start-work connectivity cache so
  repeated Start Work taps do not run a live Autotask probe every time.
- If the live or cached Autotask result is unavailable, no job may be created
  and an audit event must be recorded.
- New blank mobile jobs intentionally start without client, company, or ticket
  values. The route ignores stale or crafted pre-start client/ticket fields so
  those values can only be attached through the active-job workflow.
- Service-call starts must submit only the selected service-call ticket
  association ID plus CSRF. The route must resolve today's service-call list
  server-side for the configured `AUTOTASK_RESOURCE_ID`, verify the selected
  association belongs to that list, then populate the job from the provider's
  ticket/client data. Do not trust browser-submitted ticket number, title,
  description, client name, company ID, or work-location values for this path.
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
selection from the open-ticket picker. The mobile page does not expose a manual
active-save button; client, work-location, and summary edits are saved through
CSRF-protected background requests as the user changes them.

The mobile active-job ticket number is not a manual text entry. The open-ticket
picker posts the clicked ticket number to `POST /jobs/{job_id}/ticket`. That
route uses the recently loaded server-side open-ticket selection cache when it
is still fresh, falls back to a live Autotask lookup when needed, verifies the
submitted ticket belongs to that safe list, stores the ticket number, title,
and bounded ticket description, and records an audit event. When an active job
has no ticket number, the mobile page shows the open-ticket panel under the
client field. The panel itself is the ticket-loading control while no ticket
options have been loaded; clicking or pressing Enter/Space on the panel saves
the current active client fields before querying Autotask and shows the shared
spinner loading state while the request is in flight. A job that already has a
saved client auto-loads the picker. After selection, the browser should
immediately hide the open-ticket panel and show the selected ticket number,
ticket title, and ticket description in Work in Progress without waiting for a
page reload.

The work-location switch is intentionally not written into `summary_notes` or
the mobile textarea. Store the mode on the job and let Autotask submission
prefix `summaryNotes` with `Remote` or `On-Site`. Review detail is the
exception: it displays the complete Autotask summary with that prefix so the
reviewer can correct Remote versus On-Site before accepting or editing an
existing Autotask entry. Save/accept handlers must parse the visible prefix back
into `work_location` and keep stored local notes unprefixed.

The mobile start panels show today's Autotask service calls when an active job
slot is available. The page should render immediately with a **Loading service
calls...** state, then `job_logger/static/mobile.js` loads `/mobile/service-calls`
to fetch safe card data. Service-call options are provided by
`list_todays_service_calls_for_resource()`, which derives Remote/On-Site from
the service-call details text. Each rendered card should stay compact and show
only the client name, Remote/On-Site label, and associated ticket title, with
different Remote and On-Site coloring for quick scanning. Use the specific
`.service-call-option-button.service-call-location-*` styling hooks so these
cards do not regress to the generic grey button treatment. Clicking a service
call starts an active job with the associated ticket number, ticket title,
bounded ticket description, client name, company ID, and detected work-location
mode.

The `/mobile/service-calls` endpoint is only for drawing already-verified
candidate cards in the browser. `POST /jobs/start/service-call` must still
re-read today's provider list and verify the submitted service-call ticket
association ID before creating a job. Mobile forms that navigate or redirect,
including start, service-call start, end, rounded-start adjustment, and active
delete, should show the shared loading overlay once a submit is accepted so slow
Autotask lookups do not look like ignored taps.

Selected ticket descriptions on mobile are read-only Autotask context. Long
descriptions should stay escaped, bounded to an internal scroll area, and
available in full through scrolling inside the description box instead of
expanding the entire Work in Progress card indefinitely. Phone-sized layouts
cap the visible description box at about 50 text lines, while wider layouts can
use the larger desktop cap.

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
  text is best-effort from the buffered media snapshot. Browser-side partial
  stream messages must update status only, not the editable summary textarea.
- The faster-whisper provider passes `FASTER_WHISPER_INITIAL_PROMPT` into
  `model.transcribe()` when configured. The default prompt asks the model to
  render dictated punctuation words as symbols and paragraph breaks instead of
  spelling those words, but this remains a model-formatting hint rather than a
  guaranteed post-processing rule.
- Clicking **Stop recording** ends browser capture, lets `MediaRecorder` flush its
  final chunk, sends WebSocket `finish`, and keeps the control disabled while
  the status line shows **Sending data to server...**, then **Converting audio
  to text...**, then **Conversion complete.** after the final transcript is
  returned and pasted into the summary field. Final chunk acknowledgements from
  the server must not move the stopped UI back to **Recording audio...**. The legacy
  `POST /jobs/{job_id}/description/audio` endpoint remains as a compatibility
  upload path, but the mobile UI should use the WebSocket stream.
- Raw audio is not permanently stored by default.
- Transcription text updates the same summary field that review and Autotask
  submission use. The final streamed transcript replaces the current summary
  field in one browser update even when manually typed notes are already
  present.

Manual summary notes typed in the textarea must be preserved when active job
changes are saved or work is ended.

Manual summary autosave must not replace the focused mobile textarea with the
server-normalized response. The server trims persisted notes for storage and
Autotask payloads, but trailing whitespace in the active textarea can be normal
typing state between words on mobile keyboards.

## Review Flow

The review page is `/review`, implemented by `job_logger/routes/review.py`,
`job_logger/templates/review.html`, and `job_logger/static/review.js`.

Review supports:

- Selecting jobs from the review list.
- Viewing the selected ticket number and client name as read-only Autotask
  identity fields.
- Editing ticket status, start date/time, end date/time, and summary notes
  before successful Autotask submission.
- Automatically saving edits without a ticket number.
- Saving active jobs without an end date/time.
- Accepting or retrying submission only when the ticket number and required
  submission fields are present.
- Looking up open Autotask tickets for the stored selected company ID or client
  name.

Ticket number is intentionally required only before Autotask submission, not for
ordinary save operations.

The review summary textarea displays the complete Autotask `summaryNotes`
string, including the leading Remote or On-Site prefix. Review save, accept,
retry, and submitted-entry edit handlers must parse that prefix back into the
stored work-location mode and keep the persisted note body clean. This allows
the operator to correct the final Autotask notes without making ticket/client
identity editable.

The review detail form does not expose a manual Save button. Editable review
fields are saved through debounced background posts to `POST /review/{job_id}/save`.
The route still supports normal form posts for compatibility, and the Accept,
Retry, Reject, and Force purge actions remain explicit workflow actions.

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

After a job is successfully submitted to Autotask, ticket/client identity and
workflow actions remain protected. The UI must keep ticket selection,
accept/resend, retry, reject, and force-purge controls hidden or blocked. Date,
start time, end time, summary notes, and ticket status can stay editable only
when the submitted detail shows **Edit Entry**. That button must call the
submitted-entry update route so the existing Autotask `TimeEntries` row is
patched before local values are kept. The submitted detail can also show
**Delete From Autotask**, which deletes the external time entry and moves the
local job back to review only after Autotask confirms the delete. This action
must not delete the local job, audit events, or submission attempts.

The review detail uses one local job date with start and end times. Jobs do not
span multiple dates; validation must reject edits where the end time is not
after the start time on that same date. Keep the audit timeline collapsed by
default with an expandable detail section.

## Job Status Expectations

Jobs must never disappear silently. Prefer explicit workflow states, archived
states, rejected states, failed submission states, or audited purge paths.

Force purge exists for strict cleanup from review detail, but active jobs cannot
be purged from that endpoint. Active jobs have the separate audited delete route
described above. Successfully submitted Autotask jobs also cannot be purged
because local history must stay tied to the external time entry. Use the audited
Edit Entry or Delete From Autotask paths for submitted-entry corrections instead
of expanding local destructive behavior.

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
