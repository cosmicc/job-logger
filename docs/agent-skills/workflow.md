# TicketPilot Agent Skill: Workflow

Read this file before changing mobile work entry, active job behavior, review
behavior, job statuses, time rounding, or job-related database fields.

## Core Service Boundary

`ticket_pilot/services/jobs.py` is the workflow authority. Routes should collect
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

The work-entry home page is `/work`, implemented by
`ticket_pilot/routes/mobile.py` and `ticket_pilot/templates/mobile.html`.
`/home` must remain a query-preserving compatibility redirect to `/work`, and
`/home/service-calls` must remain an authenticated alias for
`/work/service-calls`. All rendered links, forms, redirects, browser requests,
and PWA metadata must use the canonical `/work` namespace.

The same route is also the full-browser Home and Work in Progress surface.
The selected mobile or desktop presentation must come from client/browser and
media behavior, not from separate route names.
When JavaScript behavior must distinguish mobile devices from the full web
version, `window.TicketPilotNavigation.isMobileDevice()` in
`ticket_pilot/static/navigation.js` is the single application detector. Reuse it
instead of creating feature-local viewport, user-agent, touch, or pointer
checks. Extend that shared helper and `tests/test_navigation_javascript.py`
when device coverage changes. Use `isNavigationAllowed()` when the separate
full-web navigation opt-in is also part of the decision. These helpers are for
presentation and convenience behavior only, never authentication or
authorization.
Use `ticket_pilot/static/desktop.css` for wider browser-only layout improvements
and leave `ticket_pilot/static/phone.css` unchanged unless the request explicitly
targets the phone or installed mobile app.

Phone-sized authenticated layouts hide the brand mark and desktop logout form.
The visible top bar should place Work and Review left-aligned for managed web
users, then right-align Help, Config, optional Diagnostics, and logout in that
order. Keep the shared authenticated top bar sticky at the top of the viewport
for the complete document scroll on every phone and full-browser page. Do not
constrain `html` or `body` to one viewport height, because that ends the sticky
containing block and lets the header scroll away. The Work button links to
`/work` and uses the same work-entry icon on
phone and full-browser navigation. Managed users marked as Admin also see
Diagnostics in the right-side phone action group, but that flag must not remove
Config or grant super-admin-only Users navigation. The config super admin sees
Users and Review on the left, with Help, Diagnostics, and logout on the right,
and must not see Config. The mobile logout button must submit the normal
`/logout` form with the rendered CSRF token. Do not wire mobile logout through
`window.close()`, `about:blank`, a GET link, or another browser-only action.
Keep the explicit desktop logout form available on non-mobile authenticated
pages. Full-browser top navigation should stay
centered for route links and use raised blue icon-and-text buttons. Full-browser
Help belongs in the right-side action group immediately to the left of the
visible **Log out** button. The authenticated desktop brand mark and favicon
must use `ticketpilot-logo-white.svg` on every dark theme and
`ticketpilot-logo-black.svg` on every light theme, with
`ticketpilot-logo-grey.svg` as the neutral fallback. Theme changes on Config
must update both immediately. The PWA manifest must use the supplied
`ticketpilot-app-icon-*` PNG files at 128, 256, 512, and 1024 pixels, and the
Apple touch link uses the 256 pixel source. Do not advertise maskable icons
unless separately supplied artwork has a tested full-bleed mask-safe
background.
Phone-sized navigation remains compact blue icon buttons with icon artwork
large enough to scan quickly, with all phone nav icons using one shared visible
size inside the compact buttons. Full-browser navigation includes a right-side
Help button with the same help icon and visible **Help** label. The Help page,
not the shared header, starts with **Ask AI for help**, then **Operational
Status**, then the current version and a raised **version changelog** button
that opens the release notes overlay. Help page cards should keep a small,
consistent gap between them on phone and full-browser layouts. When a release
date is available, Help labels it as `Released: MM.DD.YYYY`; the Help overlay
shows previous versions as full-width cards without timeline marker dots and
omits date labels for unreleased versions.
Enabled buttons and button-like navigation controls should visibly brighten on
hover. Workflow actions such as **Record**, **AI Cleanup**, finish, delete, and
review submit controls should look raised at rest and pressed in while active.
Destructive red controls must stay red on hover, using a brighter red instead
of falling back to a neutral dark hover.
When `DEV_BUILD=true`, the shared authenticated desktop and mobile headers show
the Help button in yellow, while the full-browser header version label under
the TicketPilot title appends `-DEV`, such as `v2.0.0-DEV`. Keep a small but
visible gap between the title and header version label. The `/help` page shows
the current version with `DEV`, such as `v2.0.0 DEV`. Keep the Help icon
compact so it does not crowd the mobile navigation icons.
When cached app health is degraded, every authenticated user sees an exclamation
status button in the top bar that links to `/help#operational-status`. Use
yellow for warning and red for critical, and keep specific issue details out of
the header for ordinary managed users. On phone layouts, keep the status button
in the left-side route group so Help remains immediately beside logout. The
Help page **Operational Status** card uses matching colors and shows green when
all monitored checks are operational.
The unauthenticated login page should render the sign-in form without a top app
icon or wordmark.

Browser titles use the compact application name first: the Work page is
`TicketPilot - Time Entry`, Config is `TicketPilot - Config`, Review is
`TicketPilot - Review`, and other pages follow the same
`TicketPilot - <Page>` convention.

New blank work starts through `POST /jobs/start`. A user can also start work
from an Autotask service call selected in the mobile day navigator through
`POST /jobs/start/service-call`.

Only database-managed web users can start or mutate jobs. The config super
admin can view review data but cannot start, edit, submit, delete, record audio,
or run AI cleanup because it has no Autotask resource ID.

Security and data-integrity requirements for start:

- The user must be authenticated as an enabled managed web user.
- CSRF must be valid.
- The `/work` page must render from local database state without running an
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
- Open-ticket option work-location label inferred from ticket title/description
  text, displayed as Remote, On-Site, or Not specified in the picker.
- Verified Autotask client selection while no open ticket has been selected for
  the active job. The client name and company ID must both come from the
  server-backed company search result and must verify together before they are
  saved. A saved active-job client may be replaced by another verified
  client/company until a ticket is selected.
- Summary notes.
- Entry type, either Time entry or Ticket note. Time entry is the normal
  default. Ticket note mode may be selected only before successful Autotask
  submission.
- Note title when the entry type is Ticket note. The title is required for
  submission, but may be incomplete while the active Work in Progress card is
  being edited.
- Append to resolution, defaulting on for both time entries and ticket notes.
- Work location mode, either Remote or On-Site, which is stored separately from
  the visible notes. Changing this mode for an active time entry must preserve
  the start and recalculate only the stop to the later of the work-location
  minimum or the current rounded 15-minute block.
- Local job date through the Work in Progress **Job date** calendar field. The
  selector shows `(Today)`, `(Yesterday)`, or `(Tomorrow)` inside the date box
  when the selected date is adjacent to the current app-local date. The date
  and relative label are centered together with two spaces between them, such
  as `06/29/2026  (Yesterday)`. Other dates show only the centered date. The
  app-owned calendar chooser uses **Today**, **Cancel**, and **Set** controls
  instead of the native browser picker so the visible wording is consistent.
  The selected date replaces the local date portion of the active rounded start
  time while preserving its local time.
- Rounded start time through an editable 12-hour Work in Progress **Start
  time** field that matches the Review detail start-time treatment, plus
  server-validated `-15` and `+15` minute buttons on either side of the field.
  Focusing the field should open a 15-minute dropdown centered on the currently
  selected time so earlier times are above and later times are below.
- Rounded stop time through an editable 12-hour Work in Progress **End time**
  field that matches the Review detail end-time treatment, plus
  server-validated `-15` and `+15` minute buttons on either side of the field.
  These controls must not use the full-page status overlay because the
  adjustment should feel immediate.
- Active Remote work must always show and persist a stop at least 15 rounded
  minutes after start. Active On-Site work must always show and persist a stop
  at least 1 rounded hour after start. When the job has already run beyond that
  minimum, a work-location change uses the current rounded block. The active
  save response must return the canonical start, stop, minimum, and duration so
  browser JavaScript updates the visible End time and Work Duration together.
- A centered **Work Duration** label on its own row under the Work in Progress
  start/end time controls, such as `Work Duration: 15 Minutes`,
  `Work Duration: 1 Hour`, or `Work Duration: 1.25 Hours`. The server returns
  the canonical value after active time saves, and browser JavaScript should
  update the visible value immediately when the visible start or stop time
  changes.
- Full-browser Work in Progress cards should order editable workflow cards as
  **Entry type** with **Work type**, **Job date** with **Ticket status**,
  **Start time** with **End time**, then **Work Duration** centered under the
  time row.
- Full-browser Work in Progress cards should place **Client name** and
  **Ticket number** together on the next row when a ticket number is shown.
- Full-browser Work in Progress left-side context cards should use equal
  half-width card slots, except **Ticket name** and **Ticket description**,
  which stay full width. The desktop **Ticket notes** and **Past time entries**
  buttons belong under the full-width **Ticket name**.
- Phone-sized Work in Progress should center the display-only **Client name**
  and **Ticket name** card titles and values after a ticket has been selected.
- A visible **Work in Progress** label above the selected ticket heading.
  Full-browser active cards should use that heading row for the selected ticket
  name even though the centered **Ticket name** card repeats the same value. The
  full-browser grid expects that label row so the Summary notes panel starts
  flush with the **Job date** card instead of dropping below the left-side
  cards. Keep that label prominent enough to scan quickly.

When Ticket note is selected, the Work in Progress UI must change **Job date**
to **Note Date**, hide the rounded start and rounded stop control rows while
preserving their current values for a switch back to Time entry, hide the
duration label, keep the Work type Remote/On-Site card visible but disabled
and greyed out, show the note-title field above the note-description textarea,
center the note-title label and text field, and change the finish/delete labels
to **End Note** and **Delete Note**. Shared switch pills use green for Time
entry or Remote selected states and orange for Ticket note or On-Site selected
states. If the user's **Submit from Work in Progress** preference is enabled,
the finish label should be a submit-note label while still posting through the
normal end-work route. This preference is not a workflow availability toggle;
it only chooses direct Autotask submission from Work in Progress instead of the
default review-first finish behavior.

The active job save route is `POST /jobs/{job_id}/ticket-number`. The name is
historical; it now saves active-job client and summary edits, not ticket
selection from the open-ticket picker. The mobile page does not expose a manual
active-save button; client, work-location, ticket status, local job date, and
summary edits are saved through CSRF-protected background requests as the user
changes them.

The mobile active-job ticket number is not a manual text entry. The open-ticket
picker posts the clicked ticket number to `POST /jobs/{job_id}/ticket`. That
route uses the recently loaded server-side open-ticket selection cache when it
is still fresh, falls back to a live Autotask lookup when needed, verifies the
submitted ticket belongs to that safe list, stores the ticket number, title,
and bounded ticket description, defaults the local editable ticket status to
In progress, and records an audit event. It must not patch Autotask ticket
status or perform any other remote write; Autotask writes wait until the job's
time entry is submitted or an already submitted entry is edited/deleted. When
an active job has no ticket number, the mobile page shows the open-ticket panel
under the client field. The panel itself is the ticket-loading control while no
ticket options have been loaded; clicking or pressing Enter/Space on the panel
saves the current verified active client selection before querying Autotask and shows the
shared spinner loading state while the request is in flight. A job that already
has a saved client does not auto-load the picker on mobile page open; the user
must click or press Enter/Space on the panel to start the lookup. After ticket
selection, the browser should immediately hide the open-ticket panel, make the
current client input read-only, and show the selected ticket number, ticket
title, and ticket description context in Work in Progress without waiting for a
page reload. If the selected ticket has no description, keep the description
card visible and show the standard no-description message. Mobile and review
open-ticket choices should use the same Remote/On-Site color treatment as service-call
start cards, with `.ticket-option-button` location classes, a visible location
badge, title, ticket status, and company metadata. This label is display
metadata only; do not trust it to override the active job's stored work-location
or ticket-status values.
When a selected ticket has Autotask notes or time entries, Work in Progress may
show compact **Ticket notes** and **Past time entries** buttons beside the
ticket context. On phone-sized layouts, those buttons belong under the Work in
Progress **Ticket name** card. On phone-sized Review, **Client name** belongs
directly above the centered **Ticket number** card, and a phone-only **Ticket
name** card with the split-row **Ticket notes** and **Past time entries**
buttons belongs above **Ticket description**. Review's read-only **Client
name** card should center its title and value on phone-sized layouts. Keep
each button hidden until its authenticated server lookup confirms at least one
row, and render results inside the shared closeable overlay, which should fill
the phone viewport for both ticket notes and past time entries. When Work in
Progress renders two active jobs, each job's visible **Ticket notes** and
**Past time entries** buttons should refresh as a matched mobile/desktop pair
for that job so the first active-job card cannot lose the past-time-entry
button while a hidden duplicate has the successful lookup state. The notes list is
newest-first by note creation time, and each note
selection card shows only the note title. The note selection card title area
should fit two lines and truncate longer titles inside the card. Author,
created, updated, type, and note body content belong in the selected note
detail pane. Past time-entry list cards show the resource name first-name first
and the formatted local start/stop/hours text on one larger single-line row,
and the selected time-entry detail shows a larger date/time row plus the
summary of work.

The work-location switch is intentionally not written into `summary_notes` or
the mobile textarea. Store the mode on the job and let Autotask submission
prefix `summaryNotes` with `Remote. ` or `On-Site. `. Review detail is the
exception: it displays the complete Autotask summary with that prefix so the
reviewer can correct Remote versus On-Site before accepting or editing an
existing Autotask entry. Save/accept handlers must parse the visible prefix back
into `work_location` and keep stored local notes unprefixed. Keep legacy
`Remote`, `Remote:`, `Remote -`, and matching On-Site prefixes parseable for
older review text.

The mobile start panels show Autotask service calls for a selected local date
when an active job slot is available. The page should render immediately with a
**Loading service calls...** state and no synchronous Autotask calls. After the
window `load` event, `ticket_pilot/static/mobile.js` loads `/work/service-calls`
to fetch safe card data for the current selected date. The panel has compact
previous/next day buttons with the displayed day between them; clicking that day
opens the native calendar picker. Today, yesterday, and tomorrow labels put the
relative day first, such as `Today (Saturday)`. Other date labels use the full
month, ordinal day, and weekday, such as `June 19th (Friday)`, without the year.
Service-call options are provided by
`list_todays_service_calls_for_resource(resource_id=..., local_service_date=...)`,
which derives Remote/On-Site from the service-call details text. The resource ID
must come from the enabled managed web user, not config or browser input. Each
rendered card should stay compact and show the client name, Remote/On-Site
label, scheduled local date, local start/end time range, and associated ticket
title, with different
Remote and On-Site coloring for quick scanning. Use the specific
`.service-call-option-button.service-call-location-*` styling hooks so these
cards do not regress to the generic grey button treatment. Clicking a service
call starts an active job with the associated ticket number, ticket title,
bounded ticket description, client name, company ID, and detected work-location
mode.

If the managed user enabled navigation and the verified service call is
detected as On-Site, the JSON start path may return its transient Autotask
destination only after the local job and audit event commit successfully. The
browser then opens the configured provider on a detected mobile device. Mobile
device classification must not use viewport width and must include phones,
tablets, iPads, and iPods, including iPadOS browsers that report a desktop Mac
platform. A full web browser may open automatic service-call directions only
when the user's default-off **Allow navigation on full web version** preference
is enabled. Remote or unknown service-call locations must not auto-launch
navigation. A missing destination must not undo or hide a successfully started
job.

The `/work/service-calls` endpoint is only for drawing already-verified
candidate cards in the browser. Before returning or accepting service-call
options, route code must filter out tickets that already have a local TicketPilot
job for the current managed web user with ticket status Complete or Follow up;
this local filter applies even when that job has not been submitted to Autotask
yet.
`POST /jobs/start/service-call` must still re-read the provider list for the
submitted local service-call date, apply the same local Complete/Follow up
filter, and verify the submitted service-call ticket association ID before
creating a job.
Starting from a service call stores verified ticket/client metadata and defaults
the local editable ticket status to In progress without patching Autotask ticket
status. Mobile forms that navigate or redirect, including start, service-call
start, end, rounded-start adjustment, and active delete, should show the shared
loading overlay once a submit is accepted so slow Autotask lookups do not look
like ignored taps.

Selected-ticket Work in Progress and Review context may expose a **Navigate to
Destination** button for the owning managed user when navigation is enabled and a server-side
Autotask lookup returns an address. Submitted jobs keep this read-only
convenience action. Home and effective Office buttons belong in the compact
Work summary area and remain hidden when navigation is None. Navigation buttons
must also stay hidden on full web browsers unless **Allow navigation on full
web version** is enabled. Do not request transient ticket destinations from a
full web browser while that preference is off. Device classification is a
presentation convenience only and must never authorize a workflow action.
Home, Office, and Navigate to Destination controls use the shared subtle blue
navigation-button treatment. On phone layouts, place **Navigate to Destination**
on its own full-width row immediately
above the **Entry type** pill card. Show that row only for time entries and
hide it in ticket-note mode, even when a destination is available.

Selected ticket descriptions on mobile are read-only Autotask context. Long
descriptions should stay escaped, bounded to an internal scroll area, and
available in full through scrolling inside the description box instead of
expanding the entire Work in Progress card indefinitely. Phone-sized layouts
cap the visible description box at about 12 text lines, while wider layouts use
about a 25-line cap. A selected ticket with an empty description should still
show the description card with the standard no-description message.

The active mobile card should expose only one client entry point for each job.
After an Autotask company is selected but before a ticket is selected, keep the
client search editable so the user can choose another verified company and load
that company's open tickets. After an open ticket is selected, the active job
displays the client as a read-only value and submits hidden copies only for
normal form flow. The service layer still enforces the post-ticket lock because
hidden fields and readonly inputs are not security controls.

Active jobs can be discarded through `POST /jobs/{job_id}/delete` from mobile
or through the selected review detail **Delete time entry** action. Both routes
require authentication, CSRF, and job ownership. Mobile active deletion records
`job.active.deleted`; review deletion records `job.review.deleted`. Do not use
the mobile endpoint for reviewed, submitted, or failed jobs.
In the active mobile card, the destructive mobile discard action is labeled
**Delete** for time entries or **Delete Note** for notes, and shares a row with
**End Work**, **End Note**, or the direct-submit variant to keep the Work in
Progress actions compact.
When two active jobs are present, their Work in Progress panels should use
distinct slot shading and render the most recently started job first. In
full-browser layout, keep End Work/Delete directly
under the Record/AI Cleanup row and place recording or AI cleanup status below
all action buttons.
Status chips shown in review, user management, and diagnostics should use the
shared outlined, all-caps pill style while keeping their status-specific colors.

## Ending Work

Work ends through `POST /jobs/{job_id}/end`.

Ending work requires:

- Authenticated enabled managed web user who owns the job.
- Valid CSRF token.
- Existing active job.
- Mandatory client name.
- Valid selected company ID if one is submitted.
- Current Work in Progress work-location mode.
- Current Work in Progress ticket status.
- Current entry type.
- Current append-to-resolution setting.
- Current summary notes carried from the mobile textarea.

After ending, the default workflow moves the job to review. When the owning
managed web user has enabled **Submit from Work in Progress** on `/config`,
the same end-work route changes the active finish button to **Submit to
Autotask** for time entries or a submit-note label for notes and submits the
completed job through `submit_job_to_autotask()`
after `end_job()` has assigned rounded stop time and local work date.
The option must never be described as enabling or disabling workflow
availability; it bypasses the review stop only after the same submission
requirements pass.

Direct Work in Progress submission rules:

- The preference is per-user, database-backed, and default off.
- The route must still validate ownership, CSRF, active status, client,
  selected company ID, entry type, ticket status, append-to-resolution, and
  submitted text. Time entries also require work location and rounded end time.
  Ticket notes require a note title and note description instead of start/stop
  time fields.
- The browser may copy hidden work-location and ticket-status values from the
  active form for normal UX, but the server must validate those values again.
- `submit_job_to_autotask()` remains the only submission service. Do not create
  a separate mobile-only Autotask path.
- Direct submission must require ticket number and ticket status for both
  record types. Time entries require rounded end time and non-empty summary
  notes before any Autotask call is attempted. Ticket notes require note title
  and non-empty note description before any Autotask call is attempted.
- Missing local submission fields should roll back the transaction so the job
  stays active and can be fixed in Work in Progress.
- Provider-level Autotask failures should use the existing submission-failed
  review state and safe error handling so the job can be retried from Review.
- Successfully direct-submitted jobs still appear in Review, but only for the
  submitted-entry **Submit changes** and **Delete From Autotask** actions.

## Speech-To-Text Flow

Recording is browser-side in `ticket_pilot/static/mobile.js` for active work and
`ticket_pilot/static/review.js` for review detail.

Current behavior:

- The active mobile and review-detail **Record** buttons start audio capture and
  share a compact two-button row with optional **AI Cleanup** in the Summary
  notes area. Review-detail recording remains available only for jobs that have
  not been successfully submitted to Autotask.
- The active mobile **Record** button uses an orange treatment, and the button
  label changes to **Stop recording** while browser recording is active. After
  capture stops, the disabled button returns to the **Record** label and shows
  the shared loading spinner while the recording is still being sent or
  converted.
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
- `TRANSCRIPTION_PROVIDER=faster_whisper_remote` sends the same submitted audio
  to a trusted remote faster-whisper API. Keep the local `faster_whisper`
  provider available. Remote transcription posts multipart `audio` plus safe
  model/language/beam/prompt options, accepts JSON `text`, and must keep HTTP
  endpoints on loopback/private networks or use HTTPS for public endpoints.
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
Browser summary autosaves through `/jobs/{job_id}/description/text` persist the
active job notes but must not write `job.description.browser_text_saved` audit
events, and legacy copies of that event must stay out of the Review audit
timeline. Review autosaves must not write `job.review.saved`, and legacy
copies of that event must also stay out of the Review audit timeline. Keep
audio transcription, AI cleanup, explicit active edits, review decisions, and
submission actions audited. Successful Autotask submissions should add the
visible `job.autotask.submitted` activity.

## AI Summary Cleanup

AI cleanup is an optional server-side integration controlled by
`AI_CLEANUP_ENABLED` and `AI_CLEANUP_PROVIDER`. Supported providers are
Gemini, Groq, Ollama, and LM Studio. The browser sends the current editable
summary text to a CSRF-protected cleanup endpoint; the server validates the job
state, calls `ticket_pilot/services/ai_cleanup.py`, records a metadata-only audit
event, and returns cleaned text. The cleanup route
must not submit to Autotask, change ticket/client identity, or bypass the normal
save/review/submitted-entry update workflow.
Configured `AI_CLEANUP_INSTRUCTIONS` must be sent through the selected
provider's instruction field. Keep the user-visible cleanup prompt focused on
the cleanup task, job context, and untrusted summary text.
Gemini cleanup uses the same `GEMINI_API_BASE` OpenAI-compatible endpoint
setting as AI Help, but it must keep `GEMINI_CLEANUP_MODEL` and
`AI_CLEANUP_INSTRUCTIONS` separate from the Help model and support prompt.

Mobile active jobs use `POST /jobs/{job_id}/summary/cleanup`. After a successful
response, `ticket_pilot/static/mobile.js` replaces the active summary textarea and
persists the cleaned result through the existing active description text save
endpoint. Mobile AI cleanup uses the same `.recording-status` line as save and
audio recording messages for progress, success, and failure details. Status
text stays text-only; the **AI Cleanup** button shows the shared spinner while
cleanup or cleaned-summary saving is in progress. Cleanup should not run while
audio recording or transcription is in progress.

Review detail uses `POST /review/{job_id}/summary/cleanup`. The returned text
replaces the review summary textarea. Non-submitted review jobs continue through
the existing autosave path, and cleanup waits for review audio recording or
transcription to finish. Submitted jobs do not patch Autotask automatically; the
user must still click **Submit changes** to update the existing external
Autotask record.

After a successful cleanup, the browser switches the same button to **Revert
cleanup** while the job has stored cleanup undo state. The server stores the
pre-cleanup editable text on the job so the revert option survives reloads and
navigation. Work in Progress reverts through
`POST /jobs/{job_id}/summary/cleanup/revert`; Review reverts through
`POST /review/{job_id}/summary/cleanup/revert`. Revert restores the original
textarea value, clears the undo state, and records metadata-only audit details.
Submitted Review entries may keep a pending cleaned draft for reloads, but
Autotask is still updated only by **Submit changes**. Cleanup undo state expires
after `AI_CLEANUP_REVERT_RETENTION_HOURS`, defaulting to 24 hours, and is
cleared opportunistically before Home or Review render and before cleanup or
revert routes act on a job.

## Review Flow

The review page is `/review`, implemented by `ticket_pilot/routes/review.py`,
`ticket_pilot/templates/review.html`, and `ticket_pilot/static/review.js`.

Review supports:

- Selecting jobs from the review list.
- Listing jobs newest-first with 10 rows per page. A selected job URL may choose
  the page containing that job so the selected row stays visible.
- Showing time-entry hours worked today and this week near the top of Review,
  including `0 Hours` when no time-entry work exists for those periods.
- Showing Today and Week time-entry hours as a compact boxed summary near the
  top of Work without turning it into full metric cards.
- Starting Review with equal Today, Week, and Unsubmitted cards directly below
  the navigation bar, without a page title or description. On phones all three
  cards stay on one row and abbreviate durations as `15m`, `1h`, or `1.25h`;
  full-browser cards keep complete duration labels. Unsubmitted counts time
  entries in Active, Ready for Review, or Submission Failed status only.
  Exclude ticket notes, rejected jobs, and successfully submitted jobs.
  Managed users use their owner-scoped job list; the config super admin uses
  the all-owner review list.
- Keeping full-browser Work start panels compact, with the Service calls title
  visually raised above the date picker while the date picker, list, and
  empty-state message remain tightly arranged. Phone spacing stays controlled
  by shared/mobile CSS.
- Showing per-row day-hours and week-hours totals by job owner and local job
  date/week. Ticket notes never contribute to these hour totals.
- Managed web users see and mutate only their own jobs. The config super admin
  can see all jobs in read-only mode.
- Super-admin review is the only place that shows job ownership for each row
  and selected detail; normal managed users must not see owner fields.
- Viewing the selected ticket number and client name as read-only Autotask
  identity fields.
- Saving the first client/company selection for an active job that was opened
  in Review before any client identity existed. This goes through
  `POST /review/{job_id}/client`, must verify the selected company ID and
  display name through the Autotask provider, rejects typed-only or mismatched
  names, and becomes read-only once saved.
- Editing entry type, ticket status, append-to-resolution, start date/time,
  end date/time, and summary notes before successful Autotask submission.
- Editing note title for Ticket note entries before successful Autotask
  submission. Submitted entries must reject entry-type conversion.
- Full-browser Review detail should order editable workflow cards as
  equal-width paired rows: **Entry type** with **Work type**, **Job date**
  with **Ticket status**, **Start time** with **End time**, then **Work
  Duration** centered under the time row. Full-width rows that do not share a
  row with another card should stay full width.
- Full-browser Review detail should show **Client name** and **Ticket number**
  together as the paired row above a full-width centered **Ticket name** card.
  The **Ticket notes** and **Past time entries** buttons should sit at the
  bottom of that **Ticket name** card, directly above **Ticket description**.
- Showing the rounded duration on a centered **Work Duration** row under the
  selected detail start/end time controls and updating the value from the
  server-normalized autosave response or the browser's current visible time
  values. Do not nest the duration inside the end-time label on full-browser
  layout because that makes the start and end time controls misalign.
- Recording additional audio notes on review detail before successful Autotask
  submission.
- Automatically saving edits without a ticket number.
- Saving active jobs without applying an end date/time. The review detail may
  display the active rounded stop preview from Work in Progress, but server-side
  review saves must ignore that displayed end time until the user actually ends
  the job.
- Accepting or retrying submission only when the ticket number and required
  submission fields are present.
- Editing or deleting already submitted entries that may have been created by
  Review acceptance or by direct Work in Progress submission.
- Looking up open Autotask tickets for the stored selected company ID and
  verified client name.
- Viewing read-only Autotask ticket notes and past time entries for the selected
  ticket through the same shared overlay used by Work in Progress. Each button
  must stay hidden when the job has no selected ticket or when the server
  returns no rows for that lookup. The notes list must stay title-only and
  newest-first, with safe author metadata shown in note detail instead of the
  list cards. Long note selection titles should clamp to two visible lines
  inside larger cards. Past time-entry list cards show first-name-first
  resource names plus one-line local start/stop/hours text, and the detail pane
  shows a larger date/time row plus the summary of work.

Ticket number is intentionally required only before Autotask submission, not for
ordinary save operations.

The review summary textarea displays the complete Autotask `summaryNotes`
string for Time entry mode, including the leading `Remote. ` or `On-Site. `
prefix. Review save, accept, retry, and submitted-entry update handlers must
parse that prefix back into the stored work-location mode and keep the
persisted note body clean. Ticket note mode must show the required **Note
title** field, then an unprefixed **Note description** textarea, then
**Append to resolution** directly above the action buttons. It must hide
the active Remote/On-Site choice by keeping the Work type card visible but
disabled and greyed out, change **Job date** to **Note Date**, hide the start
and end time controls while preserving their current values for a switch back
to Time entry, and hide the duration label. The review list must show each
row's Remote or On-Site mode for time entries and Ticket note for notes, and
the review detail work-location control
must rewrite the visible summary prefix when it changes on time entries. This
allows the operator to correct the final Autotask notes without making
ticket/client identity editable.
Phone-sized Work in Progress and Review detail layouts should order the editable
workflow cards as **Entry type**, **Work type**, **Ticket status**, **Job date**
or **Note Date**, **Start time**, **End time**, then **Work Duration**, while
leaving unmentioned fields in their existing relative positions, except Review
places the centered **Client name** card directly above the centered **Ticket
number** card and puts the ticket-history buttons inside the **Ticket name**
card above the ticket description. On phone-sized layouts, both ticket-history
buttons should open the same full-screen overlay.

The review detail form does not expose a manual Save button. Editable review
fields are saved through debounced background posts to `POST /review/{job_id}/save`.
The route still supports normal form posts for compatibility, and the Accept,
Retry, and local delete actions remain explicit workflow actions.
Review detail action controls should stay in the selected detail pane and render
as compact paired rows on both phone and full-browser layouts. Use no more than
two buttons per row. Pair **Record** with **AI Cleanup** under Summary notes,
pair **End Work** or **End Note** with the matching local delete label for
active jobs, pair **Submit changes** with **Delete From Autotask** for
submitted entries, and pair **Accept and Submit** with **Delete time entry** or
**Delete note** for normal unsubmitted entries.
Submission-failed jobs may use one row for **Retry** and **Accept and Submit**,
with destructive local delete on its own following row. Review detail should
place the shared **Changes saved**, recording, and AI Cleanup status line
directly below the visible workflow action rows so the newest message replaces
the previous status under all visible action buttons.

Review ticket selection persists through `POST /review/{job_id}/ticket`. The
route uses the recently loaded server-side open-ticket selection cache when it
is still fresh, falls back to a live Autotask lookup when needed, verifies the
submitted ticket number belongs to that safe list, stores the ticket number,
title, and bounded ticket description, defaults the local editable ticket status
to In progress, and records an audit event. It must not patch Autotask ticket
status or perform any other remote write. Do not trust browser-supplied ticket
title, ticket description, ticket number, client name, or company ID values on
review save/accept; the route must overlay those fields from the stored job
before validation. The empty-client active-job exception is
`POST /review/{job_id}/client`, which may save only the first client/company
while ticket number, client name, and company ID are all still unset, and only
after the Autotask provider verifies the selected ID and display name. The
review client search input must be excluded from generic review autosave so
typing a client cannot save arbitrary text or surface summary-note validation
before the user presses AI Cleanup or submits a workflow action. Once an open
ticket has been selected, the client name is locked for the job.

When a ticket is selected from Autotask lookup, store the ticket title with the
job and use it as the ticket-title detail heading. If no ticket has been
selected, the detail heading should read `Unassigned Ticket`. Older jobs that
have a ticket number but no stored title may display the ticket number as a
fallback. Once a job has a ticket number, hide the open-ticket lookup panel for
that job. Review ticket selection should update the read-only ticket number,
ticket-title heading, and read-only ticket description card in place after the
server verifies and stores the ticket. If the verified ticket has no
description, keep the card visible with the standard no-description message.

After a job is successfully submitted to Autotask, ticket/client identity and
workflow actions remain protected. The UI must keep ticket selection,
accept/resend, retry, local delete controls, and entry-type conversion hidden
or blocked, and it should not show the stored Autotask external ID in the
selected detail. Date, start time, end time, summary notes, work location,
append-to-resolution, and ticket status can stay editable for submitted time
entries only when the submitted detail shows **Submit changes**. Note title,
note description, append-to-resolution, and ticket status can stay editable for
submitted ticket notes through the same action. That button must call the
submitted-entry update route so the existing Autotask `TimeEntries` or
`TicketNotes` row is patched before local values are kept. Submit changes must
also reassert the selected local ticket status on `Tickets.status`; a
previously submitted Complete ticket may be moved to In progress before
patching the external record, then the selected final status may be applied
after the record patch. The submitted detail can also show **Delete From
Autotask**, which deletes the external Autotask record and moves the local job
back to review only after Autotask confirms the delete. This action must not
delete the local job, audit events, or submission attempts. If Delete From
Autotask fails, the selected detail may show a session-scoped local-only purge
dialog that warns the Autotask record may still exist before removing the
TicketPilot review row.

The review detail uses one local job date with start and end times, and the
**Job date** selector shows `(Today)`, `(Yesterday)`, or `(Tomorrow)` inside the
date box when applicable. The date and relative label are centered together
with two spaces between them. Other selected dates show only the centered date.
Jobs do not span multiple dates; validation must reject edits where the end
time is not after the start time on that same date. Keep the audit timeline
collapsed by default with an expandable detail section.
Time-entry duration validation must also enforce the selected work-location
minimum: Remote requires at least 15 rounded minutes, while On-Site requires at
least 1 rounded hour. Enforce this in `ticket_pilot/services/jobs.py` for active
end-work, active time edits with an end override, Review saves, Review
submission/retry, submitted-entry edits, and final Autotask submission
readiness. Ticket notes do not use start/stop time fields and are exempt.
Active Work time edits clamp the stop to the selected minimum; Review and
submitted-entry edits remain manual and reject an undersized duration instead
of silently changing it.

## Job Status Expectations

Jobs must never disappear silently. Prefer explicit workflow states, archived
states, failed submission states, or audited cleanup paths.

**Delete time entry** exists for strict local cleanup from review detail and may
delete active, ready-for-review, or failed local jobs when the current managed
web user owns the job. Successfully submitted Autotask jobs cannot use local
review cleanup because local history must stay tied to the external Autotask
record.
The only submitted-job local purge exception is the explicit fallback after
Delete From Autotask fails. Use the audited Submit changes or Delete From Autotask
paths for submitted-entry corrections instead of expanding local destructive
behavior.

## Time Rules

All user-facing dates and times use `America/Detroit`.

All user-facing times display in 12-hour `am`/`pm` format. Keep any 24-hour
values limited to internal compatibility parsing or external API payloads.

All stored timestamps are UTC.

Use `ticket_pilot/time_utils.py` for:

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
