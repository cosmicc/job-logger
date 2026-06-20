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
- Enforcing the maximum of two simultaneous active jobs per managed web user.
- Enforcing job ownership before any managed web user mutates a job.
- Assigning Job 1 and Job 2 slots.
- Updating active ticket/client/summary fields.
- Adjusting rounded active start time in 15-minute increments.
- Ending active jobs and moving them to review.
- Deleting an active in-progress job when the user explicitly discards it.
- Validating review fields.
- Applying review edits.
- Accepting/retrying Autotask submission.
- Deleting local unsubmitted jobs, including active jobs, through explicit
  review-detail cleanup.

## Active Job Flow

The mobile page is `/mobile`, implemented by `job_logger/routes/mobile.py` and
`job_logger/templates/mobile.html`.

Phone-sized authenticated layouts hide the brand mark and logout form. The
visible top bar should place the left navigation icons on the left, the version
link centered in the middle, and right-side action icons on the right. Managed
web users see Home and Review on the left, with Config and close on the right.
The config super admin sees Users, Review, and Diagnostics on the left, with
close on the right, and must not see Config. The close button is wired by
`job_logger/static/pwa.js` and should only attempt to close the installed web
app or browser tab; it must not clear the authenticated local session, submit
logout, or perform another state-changing action. The browser script should call
`window.close()` directly first because that was the working app-shell behavior,
then fall back to `about:blank` only if the document remains visible. Keep the
explicit logout form available on non-mobile authenticated pages.

New blank work starts through `POST /jobs/start`. A user can also start work
from an Autotask service call selected in the mobile day navigator through
`POST /jobs/start/service-call`.

Only database-managed web users can start or mutate jobs. The config super
admin can view review data but cannot start, edit, submit, delete, record audio,
or run AI cleanup because it has no Autotask resource ID.

Security and data-integrity requirements for start:

- The user must be authenticated as an enabled managed web user.
- CSRF must be valid.
- The `/mobile` page must render from local database state without running an
  Autotask API contactability check.
- Blank Start Work must not call Autotask before creating the local active job.
  Ticket and company data are attached later through explicit lookup flows.
- New blank mobile jobs intentionally start without client, company, or ticket
  values. The route ignores stale or crafted pre-start client/ticket fields so
  those values can only be attached through the active-job workflow.
- Service-call starts must submit only the selected service-call ticket
  association ID, the selected local service-call date, and CSRF. The route must
  resolve the service-call list server-side for that date and the logged-in
  managed web user's Autotask resource ID, verify the selected association
  belongs to that list, then populate the job from the provider's ticket/client
  data. Do not trust browser-submitted ticket number, title, description, client
  name, company ID, or work-location values for this path.
- The service layer must enforce the two-active-job limit for the current web
  user.

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
saved client does not auto-load the picker on mobile page open; the user must
click or press Enter/Space on the panel to start the lookup. After selection,
the browser should immediately hide the open-ticket panel and show the selected
ticket number, ticket title, and ticket description in Work in Progress without
waiting for a page reload.

The work-location switch is intentionally not written into `summary_notes` or
the mobile textarea. Store the mode on the job and let Autotask submission
prefix `summaryNotes` with `Remote` or `On-Site`. Review detail is the
exception: it displays the complete Autotask summary with that prefix so the
reviewer can correct Remote versus On-Site before accepting or editing an
existing Autotask entry. Save/accept handlers must parse the visible prefix back
into `work_location` and keep stored local notes unprefixed.

The mobile start panels show Autotask service calls for a selected local date
when an active job slot is available. The page should render immediately with a
**Loading service calls...** state and no synchronous Autotask calls. After the
window `load` event, `job_logger/static/mobile.js` loads `/mobile/service-calls`
to fetch safe card data for the current selected date. The panel has compact
previous/next day buttons with the displayed day between them; clicking that day
opens the native calendar picker. Service-call options are provided by
`list_todays_service_calls_for_resource(resource_id=..., local_service_date=...)`,
which derives Remote/On-Site from the service-call details text. The resource ID
must come from the enabled managed web user, not config or browser input. Each
rendered card should stay compact and show the client name, Remote/On-Site
label, local start/end time range, and associated ticket title, with different
Remote and On-Site coloring for quick scanning. Use the specific
`.service-call-option-button.service-call-location-*` styling hooks so these
cards do not regress to the generic grey button treatment. Clicking a service
call starts an active job with the associated ticket number, ticket title,
bounded ticket description, client name, company ID, and detected work-location
mode.

The `/mobile/service-calls` endpoint is only for drawing already-verified
candidate cards in the browser. `POST /jobs/start/service-call` must still
re-read the provider list for the submitted local service-call date and verify
the submitted service-call ticket association ID before creating a job. Mobile
forms that navigate or redirect, including start, service-call start, end,
rounded-start adjustment, and active delete, should show the shared loading
overlay once a submit is accepted so slow Autotask lookups do not look like
ignored taps.

Selected ticket descriptions on mobile are read-only Autotask context. Long
descriptions should stay escaped, bounded to an internal scroll area, and
available in full through scrolling inside the description box instead of
expanding the entire Work in Progress card indefinitely. Phone-sized layouts
cap the visible description box at about 12 text lines, while wider layouts use
about a 25-line cap.

The active mobile card should expose only one client entry point for each job.
After an Autotask company is selected, the active job displays that client as a
read-only value and submits hidden copies only for normal form flow. The
service layer still enforces the lock because hidden fields are not security
controls.

Active jobs can be discarded through `POST /jobs/{job_id}/delete` from mobile
or through the selected review detail **Delete time entry** action. Both routes
require authentication, CSRF, and job ownership. Mobile active deletion records
`job.active.deleted`; review deletion records `job.review.deleted`. Do not use
the mobile endpoint for reviewed, submitted, or failed jobs.

## Ending Work

Work ends through `POST /jobs/{job_id}/end`.

Ending work requires:

- Authenticated enabled managed web user who owns the job.
- Valid CSRF token.
- Existing active job.
- Mandatory client name.
- Valid selected company ID if one is submitted.
- Current summary notes carried from the mobile textarea.

After ending, the job moves to review. Do not submit time to Autotask directly
from mobile end-work. Submission happens only after review acceptance or retry.

## Speech-To-Text Flow

Recording is browser-side in `job_logger/static/mobile.js` for active work and
`job_logger/static/review.js` for review detail.

Current behavior:

- Record Audio starts audio capture and is placed above the optional AI Cleanup
  action in the active Summary notes area. Review detail shows the same record
  control for jobs that have not been successfully submitted to Autotask.
- The Record Audio button uses an orange treatment, and the button label changes
  to **Stop recording** while browser recording is active. After capture stops,
  the disabled button returns to the **Record Audio** label and shows the shared
  loading spinner while the recording is still being sent or converted.
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
- Recording, streaming, transcription, and cleanup progress messages are plain
  status text without inline spinners. The shared spinner belongs on the active
  button itself, such as the disabled record button after capture stops or the
  AI Cleanup button during cleanup.
- Clicking **Stop recording** ends browser capture, lets `MediaRecorder` flush
  its final chunk, sends WebSocket `finish`, and keeps the control disabled
  with a button spinner while the status line shows **Sending data to
  server...**, then **Converting audio to text...**, then **Conversion
  complete.** after the final transcript is returned and pasted into the
  summary field. Final chunk acknowledgements from the server must not move the
  stopped UI back to **Recording audio...**. The legacy
  `POST /jobs/{job_id}/description/audio` endpoint remains as a compatibility
  upload path, but the mobile UI should use the WebSocket stream.
- Raw audio is not permanently stored by default.
- Transcription text updates the same summary field that review and Autotask
  submission use. The final streamed transcript replaces the current summary
  field in one browser update even when manually typed notes are already
  present.
- Review-detail recording is available only before successful Autotask
  submission. The server rejects submitted jobs even if a crafted WebSocket
  request bypasses the hidden button.

Manual summary notes typed in the textarea must be preserved when active job
changes are saved or work is ended.

Manual summary autosave must not replace the focused mobile textarea with the
server-normalized response. The server trims persisted notes for storage and
Autotask payloads, but trailing whitespace in the active textarea can be normal
typing state between words on mobile keyboards.

## AI Summary Cleanup

AI cleanup is an optional server-side integration controlled by
`AI_CLEANUP_ENABLED` and `AI_CLEANUP_PROVIDER`. Supported providers are
Gemini, Groq, server-local Ollama, and server-local LM Studio. The browser
sends the current editable summary text to a CSRF-protected cleanup endpoint;
the server validates the job state, calls `job_logger/services/ai_cleanup.py`,
records a metadata-only audit event, and returns cleaned text. The cleanup route
must not submit to Autotask, change ticket/client identity, or bypass the normal
save/review/Edit Entry workflow.

Mobile active jobs use `POST /jobs/{job_id}/summary/cleanup`. After a successful
response, `job_logger/static/mobile.js` replaces the active summary textarea and
persists the cleaned result through the existing active description text save
endpoint. Mobile AI cleanup uses the same `.recording-status` line as audio
recording for progress, success, and failure details. Status text stays
text-only; the **AI Cleanup** button shows the shared spinner while cleanup or
cleaned-summary saving is in progress. Cleanup should not run while audio
recording or transcription is in progress.

Review detail uses `POST /review/{job_id}/summary/cleanup`. The returned text
replaces the review summary textarea. Non-submitted review jobs continue through
the existing autosave path, and cleanup waits for review audio recording or
transcription to finish. Submitted jobs do not patch Autotask automatically; the
user must still click **Edit Entry** to update the existing external Autotask
time entry.

## Review Flow

The review page is `/review`, implemented by `job_logger/routes/review.py`,
`job_logger/templates/review.html`, and `job_logger/static/review.js`.

Review supports:

- Selecting jobs from the review list.
- Managed web users see and mutate only their own jobs. The config super admin
  can see all jobs in read-only mode.
- Super-admin review is the only place that shows job ownership for each row
  and selected detail; normal managed users must not see owner fields.
- Viewing the selected ticket number and client name as read-only Autotask
  identity fields.
- Editing ticket status, start date/time, end date/time, and summary notes
  before successful Autotask submission.
- Recording additional audio notes on review detail before successful Autotask
  submission.
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
Retry, and **Delete time entry** actions remain explicit workflow actions.

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
accept/resend, retry, and local **Delete time entry** controls hidden or
blocked. Date, start time, end time, summary notes, and ticket status can stay
editable only when the submitted detail shows **Edit Entry**. That button must
call the submitted-entry update route so the existing Autotask `TimeEntries`
row is patched before local values are kept. The submitted detail can also show
**Delete From Autotask**, which deletes the external time entry and moves the
local job back to review only after Autotask confirms the delete. This action
must not delete the local job, audit events, or submission attempts.

The review detail uses one local job date with start and end times. Jobs do not
span multiple dates; validation must reject edits where the end time is not
after the start time on that same date. Keep the audit timeline collapsed by
default with an expandable detail section.

## Job Status Expectations

Jobs must never disappear silently. Prefer explicit workflow states, archived
states, failed submission states, or audited cleanup paths.

**Delete time entry** exists for strict local cleanup from review detail and may
delete active, ready-for-review, or failed local jobs when the current managed
web user owns the job. Successfully submitted Autotask jobs cannot use local
review cleanup because local history must stay tied to the external time entry.
Use the audited Edit Entry or Delete From Autotask paths for submitted-entry
corrections instead of expanding local destructive behavior.

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
