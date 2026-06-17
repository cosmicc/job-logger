# Changelog

All recorded changes to Job Logger are documented in this file.

## Unreleased

- Updated the mobile recording control so **Record Audio** becomes a red **Stop
  Recording** button only while browser capture is active. Clicking it again
  stops capture, returns the button to idle styling, and leaves the existing
  WebSocket stream/transcode status running until the transcript is returned to
  summary notes.
- Added automatic phone and desktop stylesheet loading, tightened the review
  detail `-15` / time / `+15` controls so the time input no longer pushes the
  buttons out of line, and added read-only selected-ticket description cards on
  mobile Work in Progress and review detail. The description is captured from
  the server-verified Autotask ticket lookup and is not used as submitted time
  notes.
- Started source-controlled application versioning at `0.0.1`, aligned package
  metadata to that value, and displayed the current version on the authenticated
  diagnostics page.
- Added a persisted Remote/On-Site switch to the mobile Work in Progress card,
  defaulting to Remote. The selected mode stays out of the visible summary text
  and is prefixed onto Autotask `summaryNotes` only when a time entry is
  created. Kept the active open-ticket picker visible before ticket selection,
  added a manual **Find tickets** button inside it, and made client selection
  save in the background before automatically loading open tickets. Selecting a
  ticket now hides the open-ticket list immediately, updates the saved ticket
  number/title in place on mobile and review, and shows the selected ticket name
  as a Work in Progress card.
- Made the mobile Work Type switch a compact side-by-side segmented control so
  Remote and On-Site no longer render as tall stacked radio controls.
- Moved the editable active-job client name field above the Work in Progress
  open-ticket list so the ticket choices always appear directly under the
  client they belong to.
- Restyled the Work in Progress Remote/On-Site selector as a compact switch,
  made the rounded-start `-15` and `+15` controls square buttons on either side
  of the time, and narrowed Autotask open-ticket picker queries so they request
  a small server-filtered open-ticket page instead of every ticket for the
  selected company.
- Replaced the mobile Work in Progress rounded-start dropdown with compact
  `-15` and `+15` minute buttons on either side of the displayed rounded start
  time.
- Added a short Start Work Autotask health cache so repeated job starts do not
  run the full live Autotask connectivity probe every tap; the debug API test
  still performs a fresh live check.
- Switched the mobile recorder to chunked WebSocket audio streaming. The server
  authenticates the session, validates CSRF in the first stream message before
  accepting audio bytes, starts best-effort interim transcription when the first
  chunk arrives, saves the final transcript on `finish`, keeps raw audio
  in-memory only, and adds Nginx WebSocket proxy support for the stream route.
- Simplified the mobile recorder to one button. Stopping capture now flushes
  the final browser audio chunk, sends the WebSocket finish message, and keeps
  the control disabled while the streamed transcription completes.
- Added a short server-side cache for open-ticket selection lists so choosing a
  ticket that was just loaded does not perform a second live Autotask ticket
  query, and made the mobile picker hide immediately on selection before the
  verified save response returns.
- Removed `billingCodeID` / Allocation Code from live Autotask `TimeEntries`
  creation so ticket time entry submissions use Autotask defaults and do not
  require Allocation Code edit permission.
- Made review-page ticket number and client name read-only identity fields,
  persisted review ticket selections through a CSRF-protected server endpoint,
  and kept review save/accept from trusting crafted form values for selected
  Autotask ticket or client data.
- Added an audited mobile **Delete** action for discarding an active in-progress
  job before it reaches review history.
- Improved Autotask submission error handling so ticket-status updates and
  `TimeEntries` creation show bounded body-level API details when Autotask
  returns useful error text with HTTP 500 responses.
- Improved Autotask diagnostics so the debug API test records the first failed
  operation, adds Companies/Tickets-specific troubleshooting tips for Autotask
  HTTP 500 responses, and makes `scripts/discover_autotask_ids.py` print
  non-fatal workflow endpoint preflight results alongside ID discovery. The
  diagnostics now safely surface bounded Autotask body-level permission messages
  when Autotask wraps permission denials in HTTP 500 responses.
- Documented that blank `AUTOTASK_IMPERSONATION_RESOURCE_ID` omits the
  `ImpersonationResourceId` header, which lets Autotask evaluate the API user's
  own Companies/Tickets permissions.
- Fixed Autotask POST query pagination so Companies/Tickets lookup follows
  `nextPageUrl` with POST and the original query body instead of GET, avoiding
  HTTP 405 failures when loading open tickets.
- Cleaned up the mobile Work in Progress card so each active job has one client
  entry point, locks a selected Autotask client as read-only during active work,
  shows populated client and ticket values in the same rounded metric-card style
  as start-time values, auto-loads open tickets without a manual find button,
  places the open-ticket list directly under the selected client and hides it
  after ticket selection, keeps the active-job delete button aligned with the
  surrounding action buttons,
  verifies active ticket selections through a server-side open-ticket lookup so
  the selected ticket title drives the review heading, moves **Save Active
  Changes** below summary notes, uses bounded 15-minute rounded-start
  adjustment controls, and keeps Job 1/Job 2 on the same shared layout. Fixed the active
  ticket-number pattern so selected Autotask ticket values like
  `T20260504.0018` pass browser validation.
- Added stored Autotask ticket titles so the review detail heading shows the
  selected ticket name, leaves untitled jobs as `Unassigned Ticket`, and hides
  open-ticket lookup panels after a job has a ticket number.
- Removed pre-start mobile client and ticket-number entry fields, made mobile
  job starts create blank active jobs, and changed active mobile ticket numbers
  to read-only values populated and saved by selecting an open Autotask ticket.
- Tightened review time-step rollover so crossing midnight changes the
  America/Detroit work date at local `12:00 AM`.
- Added support for two overlapping active jobs (Job 1 and Job 2) with explicit
  slot assignment, added client reference capture at job start, and preserved
  completion behavior when manual summary notes are typed on the mobile screen by
  forwarding the current mobile summary text with job-end submission.
- Made client name required when ending work and surfaced that value in review rows;
  removed the separate Autotask status column from the review list so submission
  state now appears as a workflow status chip.
- Allowed review edits (summary/time/client/ticket status) to be saved when the
  ticket number is blank; ticket number is now enforced only when saving to
  Autotask on accept/retry.
- Allowed active jobs to be saved from the job list without stop date/time by
  making end fields optional only while the job is active.
- Added a mobile active-job save action for ticket number, client name, and current
  summary notes so edits can be saved before pressing End Work.
- Added a read-only Autotask discovery script for role IDs, billing code IDs, and
  ticket status picklist IDs using local `.env` configuration without printing
  credentials.
- Added Docker-configurable faster-whisper CPU threads and app memory limit
  defaults of 8 threads and 8g for local transcription.
- Documented the recommended Docker host size of at least 8 CPU cores and 10 GB
  of RAM for reliable local faster-whisper transcription.
- Added review-side Autotask open-ticket lookup by stored client name, allowing
  reviewers to select a ticket and fill the ticket number field automatically.
- Added mobile Autotask company search by client name, stored selected Autotask
  company IDs on jobs, and used the selected company for mobile/review open-ticket
  lookup.
- Made live Autotask mandatory for production job starts, blocked new work when
  Autotask connectivity/configuration fails, and replaced the debug ticket-reset
  action with a safe Autotask API connectivity test and troubleshooting tips.
- Added two-hour in-process positive caching for Autotask company lookups and
  selected company metadata, kept ticket status labels and other lookup caches at
  15 minutes, and avoided treating empty company cache results as authoritative;
  Autotask company/ticket queries now request `MaxRecords=500`, follow pagination
  links, and fail safely instead of silently truncating unexpectedly large result
  sets.
- Expanded agent documentation with a current app structure map, workflow
  summary, mandatory Autotask dependency notes, and dedicated workflow,
  Autotask, and security agent skill files.
- Updated the mobile workflow recording controls, added 15-minute review time
  increment controls for start/end times, and surfaced client context in the
  review flow.
- Added mobile in-progress rounded-start adjustments so the active job start time can
  be changed in +/-15-minute increments directly from the work card.
- Simplified networking configuration so only `NGINX_PUBLIC_PORT` needs to be set
  for deployment: app and Nginx internals are now fixed to `8000` and `80`
  respectively, and optional internal/external port overrides were removed from
  runtime configuration and diagnostics.
- Updated Nginx host binding and remote-tunnel documentation so a Cloudflare
  dashboard service URL can target the server's LAN/internal IP on
  `NGINX_PUBLIC_PORT`; removed the local `cloudflared --url` override so the
  remotely-managed tunnel route remains authoritative.
- Baked the Nginx proxy template into a local Nginx image and expanded tunnel
  diagnostics to detect public-host `APP_ALLOWED_HOSTS` mismatches, preventing
  the stock Nginx 404 page from masking a missing proxy configuration.
- Added a new authenticated `/debug` page for troubleshooting Autotask connectivity:
  includes a masked config snapshot, last-200 submission attempts, sanitized
  request payloads, and per-attempt success/failure indicators.
- Added a debug action to clear all ticket-related job fields and submission
  attempts from the `/debug` page so troubleshooting can begin from a clean
  state without deleting the whole database.
- Added a per-job **Force purge** button on the review detail pane and a
  matching `/review/{job_id}/purge` endpoint to permanently delete a selected job
  (plus related submission attempts) for strict cleanup.
- Removed the recent-jobs list from the mobile entry page so `/mobile` stays focused
  on the active work flow only.
- Added mobile audio recording controls on `/mobile` so users can capture notes
  during active work and submit the session for transcription.
- Removed the pre-start Autotask ticket number input from `/mobile`; starting a new
  entry now only presents the Start Work action.
- Increased spacing between the mobile ticket number entry field and the Start Work
  button for clearer separation and easier tapping on mobile.
- Removed `APP_PASSWORD_HASH` and Argon2 password-hash handling so deployments
  use only `APP_USERNAME` and `APP_PASSWORD`; set Cloudflare Access enforcement
  off by default unless explicitly enabled after Access is configured.
- Added optional Autotask ticket number capture on the mobile page before or
  during active work, with server-side `TYYYYMMDD.####` validation and review
  prefill.
- Improved mobile flow so active jobs show a ticket field without a manual save
  button, description notes are editable in-page and synced from both typing and
  speech-to-text recording, and the review list now highlights and loads the
  selected job with clear row-level Autotask submission status.
- Unified note text so transcribed content now populates the same `summary_notes`
  field used for review and Autotask submission, removing the separate
  description field in the review workflow; added dark theme as the default.

- Added the initial `AGENTS.md` project instructions for the Dockerized Python
  Job Logger application.
- Documented the security-first architecture, Cloudflare Tunnel deployment
  expectations, PostgreSQL storage requirements, Autotask review workflow,
  speech-to-text provider configurability, time rounding rules, audit logging
  requirements, Python standards, and changelog policy.
- Created the initial FastAPI application, Docker stack, PostgreSQL/Alembic
  schema, mobile capture page, desktop review page, speech-to-text provider
  interface, Autotask provider interface, CSRF-protected local authentication,
  audit logging, and tests.
- Replaced the OpenAI speech-to-text provider with local faster-whisper
  transcription and updated Docker/environment variables for local model
  caching.
- Made the `cloudflared` Docker service part of the default Compose stack,
  required `CLOUDFLARE_TUNNEL_TOKEN` for startup, restricted local app and
  tunnel metrics ports to `127.0.0.1`, and updated tunnel deployment
  documentation.
- Added tunnel 502 troubleshooting documentation and a `/moble` typo redirect
  to the mobile page.
- Added a tunnel diagnostic script and clarified that Cloudflare Tunnel should
  route to `http://app:8000` when `cloudflared` runs in the Compose stack,
  regardless of the host-side `APP_EXPOSE_PORT` value.
- Added `APP_INTERNAL_PORT` so the Uvicorn/container port can be changed from
  the default `8000` without confusing it with the host-side
  `APP_EXPOSE_PORT` mapping.
- Added an Nginx reverse-proxy container as the web front end for Cloudflare
  Tunnel, moved host troubleshooting traffic to Nginx, and updated tunnel
  diagnostics to validate `cloudflared -> nginx -> app` connectivity.
- Split Nginx self-health from FastAPI upstream health so Compose can start the
  reverse proxy reliably while still keeping explicit diagnostics for
  `nginx -> app` connectivity.
- Relaxed compose startup when a Cloudflare tunnel token is missing by moving the
  token requirement into container runtime checks and documenting a local debug
  path that runs `app`, `db`, and `nginx` without tunnel connectivity.
- Updated Nginx health checks to avoid false unhealthy states when optional
  network tools are absent inside the container image.
- Updated `cloudflared` compose command handling to work with Cloudflare's
  distroless image (no `/bin/sh`) and added a fallback tunnel-token value so
  startup logs remain actionable when the token is not set.
- Updated tunnel diagnostics to focus on the running cloudflared instance rather
  than invalid container checks for `/nginx-health` and to report clear token
  state; this helps separate network routing failures from container startup
  misconfiguration.
