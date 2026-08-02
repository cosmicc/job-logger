# AGENTS.md

## Project Overview

This repository is for a Dockerized Python web application named TicketPilot.
Its formal long name is **Ticket Pilot for Autotask**; use `TicketPilot` as the
compact UI, code, package, and deployment name. Production use depends on the
Autotask service and valid Autotask API access.
The application provides a mobile-first web workflow for recording work time,
recording spoken job descriptions, reviewing recorded jobs, and creating
Autotask time entries, customer-visible ticket notes, or project-task notes
after review and acceptance. A work target may be either a Service Desk ticket
or a project task; never treat the parent project as the target of a
project-task work record.

The application will be exposed through Cloudflare Tunnel using `cloudflared`.
The Docker deployment must include the Python web application, PostgreSQL, and
`cloudflared` when practical for local production deployment.

All design and implementation decisions must prioritize security first.

## Security Requirements

Security is the highest priority for this project.

Use both Cloudflare Access and application-level authentication for
internet-facing deployments when the Cloudflare Access application is
configured. Cloudflare Access protects the public hostname before traffic
reaches the application. The Python application must still enforce its own
authenticated server-side sessions and authorization checks, and production
startup must not depend on the optional Cloudflare Access header gate being
enabled.

`APP_USERNAME` and `APP_PASSWORD` define the config super admin. That account
is for user management, diagnostics, backup/restore, and read-only job review;
it must not start, edit, submit, delete, record, or AI-cleanup work entries
because it has no Autotask resource ID. Normal work must be performed through
database-managed web users created on `/users`.
The config super admin and managed web users explicitly marked as Admin may see
and use `/diagnostics` and `/diagnostics/*`, including all Diagnostics buttons
and options. `/debug` and `/debug/*` remain authenticated compatibility aliases,
but all rendered links, forms, and redirects must use `/diagnostics`.
The managed-user Admin flag grants only Diagnostics access. It must not grant
`/users`, super-admin review scope, or any extra job workflow permissions.
Managed web users without the Admin flag must receive 403 for direct debug
requests.

Managed web users must have a full name, unique username, password hash, and
Autotask resource ID. They may also store the email address returned by the
selected Autotask Resource lookup and an optional default active service-desk
role ID selected from that resource's active Autotask `ResourceServiceDeskRoles`.
The `/users` page presents managed accounts in a table with visible stored email
and default-role metadata, last successful managed-user login time, green/red
Device sign-in passkey status icons, Admin status, and icon-only row actions
for edit, enable/disable, delete, send password reset email, and resend welcome
email. The visible user list must not show internal Autotask resource ID or role
ID values, and it must never show archived/hidden deleted users, though add/edit
forms may still query and save those values for internal use. Password reset and
welcome-email row actions must be disabled or blocked for disabled users. The
Enabled/Disabled status pill itself is a CSRF-protected toggle: clicking Enabled
disables that user and signs out old sessions, and clicking Disabled re-enables
that user.
delete row action fully removes a user that has no linked jobs. If the user has
linked jobs, delete archives and hides the account, invalidates sessions, removes
passkeys, reset tokens, and preferences, keeps linked jobs attached to the same
hidden row, and restores that row automatically when a new user is added with
the same Autotask resource ID, even if the name or username is different. The
full-browser user table should use the full panel width, compact fixed columns,
and ellipsized long values so rows fit without wrapping into multiple lines.
The add form may suggest usernames from full names, such as `jblow` for
`Joe Blow`, and add/edit forms may query Autotask Resources and active
service-desk roles for super-admin-only resource and role pickers. Add/edit
forms also expose the default-off Admin checkbox that grants full Diagnostics
access only. The role picker should show Autotask `Roles.name` labels when that
metadata is readable while storing only the selected numeric `roleID` on the
managed web-user row.
The add form includes a default-on **Send welcome email** option. When checked,
it sends the new user's stored email address a plain-text welcome email with the
configured `APP_PUBLIC_BASE_URL`, username, temporary-password instructions,
mobile install steps, Device sign-in guidance, and `ADMIN_CONTACT_EMAIL` when
configured. Account emails should call the app **TicketPilot**. The
welcome email must never include the temporary password, and
user creation must still succeed when welcome-email delivery is skipped or
fails. Audit only safe outcome metadata such as user ID, username, provider,
email-saved state, and bounded delivery errors.
Store only salted password verifiers, never raw managed user passwords.
Managed-user passwords must be at least 8 characters and include lowercase,
uppercase, number, and symbol characters. Passwords created or reset by the
config super admin are temporary: the managed user must change that password on
the next sign-in before using any page other than `/config/password` or logout.
Changing the password from `/config` clears the temporary-password requirement.
Disabled web users must be blocked from new logins and from using old signed
sessions. Hidden archived web users must stay blocked from every login path and
must not appear in `/users`; the login screen explains that the account is
disabled only after the correct password is submitted. `ADMIN_CONTACT_EMAIL` is
an optional Docker/env
setting shown in disabled-account login/session messages and under successful
AI Help answers. When it is unset, disabled-account messaging must fall back to
a generic app-administrator contact without exposing account existence before a
password or passkey assertion verifies.
Self-service password reset is controlled by `PASSWORD_RESET_ENABLED` and must
stay hidden from the login page while disabled. When enabled, `/forgot-password`
and `/reset-password/{token}` remain behind Cloudflare Access and use
application CSRF protection. The reset request flow must not reveal whether an
email address belongs to an account. Send a reset email only when exactly one
enabled managed web user matches the submitted email address. Disabled users,
zero matches, and multiple enabled matches all receive the same generic browser
message without creating a reset token or sending email. Store only HMAC-SHA256
reset-token hashes keyed by `APP_SECRET_KEY`, never raw reset tokens or full
reset URLs. Reset links are single-use, expire after
`PASSWORD_RESET_TOKEN_TTL_HOURS` defaulting to 24, clear
`password_must_change` through the normal managed-user password-change helper,
and invalidate the user's existing signed sessions after success. Reset requests
must verify Cloudflare Turnstile server-side when enabled, use independent
IP/email/account throttles, and audit only safe metadata such as email hashes,
user IDs, usernames, reset row IDs, provider names, delivery results, and
rate-limit scopes. Consecutive syntactically valid reset emails that do not
resolve to exactly one enabled user are counted by trusted enforcement IP.
At `PASSWORD_RESET_FAILED_ATTEMPTS_BLOCK_THRESHOLD`, defaulting to 3, the IP
must enter the normal local lockout and, when configured, the app-managed
Cloudflare block list. Missing, disabled, and duplicate matches all count;
one unique enabled match resets the counter. Keep browser responses generic,
store no raw submitted email in the counter, and honor the Cloudflare IP
allowlist. `TURNSTILE_ENABLED=false` is allowed for password reset in
development and production; when Turnstile is disabled, the reset flow must
still use CSRF, Cloudflare Access when configured, rate limits, generic
non-enumerating responses, and HMAC-stored token hashes.
The super-admin `/users` password-reset email row action may create and send a
reset link even when `PASSWORD_RESET_ENABLED=false` hides public self-service
reset requests. Token lookup and password-change completion must still validate
the HMAC token, expiry, single-use state, CSRF, and password rules.
Password reset mail delivery is selected by `MAIL_MODE`. `smtp` preserves the
existing SMTP transport and requires SMTP host/port settings when reset mail is
enabled. `smtp2go` sends through SMTP2GO's HTTPS API and requires
`MAIL_SMTP2GO_API_KEY`; the API key must never be logged or committed.
When Turnstile is enabled, the static forgot-password page loads Cloudflare's
standard `api.js` script, does not use the implicit `cf-turnstile` auto-render
class, and renders the widget through the local password reset script with
`turnstile.render()` only after the Cloudflare API is available. The local
script may retry the explicit `api.js?render=explicit` URL if the standard API
script fails before rendering. Do not call `turnstile.ready()` from a deferred
script. Keep the reset button disabled until a non-empty Turnstile token
exists; server-side verification remains mandatory and must reject mismatched
Turnstile action or public hostname values returned by Cloudflare Siteverify.
Forgot-password Turnstile browser diagnostics may post CSRF-protected,
same-origin, sanitized lifecycle events to the app for logging. Those logs may
include event names, script host/path metadata, callback state, token length,
render state, request IP, and user agent, but must never include raw Turnstile
tokens, email addresses, reset URLs, cookies, secrets, site keys, or API keys.

Local authenticated sessions must expire after `APP_SESSION_TIMEOUT_HOURS`,
measured in hours. The configured value controls both the signed session cookie
lifetime and the server-side authenticated-at timestamp check. Expired sessions
must be cleared and forced through login again.
The login page has a default-off **This is a public device** option for password
sign-in. It appears below the forgot-password link and keeps the explanatory
copy in a hover/title hint instead of a persistent text block. While checked,
the Device sign-in button must be visibly greyed out, disabled, and unclickable;
unchecking it must restore the normal Device sign-in button state.
Public-device sessions must expire after 15 minutes of inactivity, refresh the
inactivity timestamp only after valid requests, suppress the post-login Home
Device sign-in setup prompt, and reject new passkey registration while that
session is active. Public-device mode must not weaken normal authentication,
CSRF, disabled-user, or session-timeout checks.
Diagnostics may also invalidate all managed web-user sessions with a
CSRF-protected button. That action must not sign out the config super admin
because the super admin is not a managed web user. A managed Admin user who
presses it is included because that account is a managed web user.

Managed web users may register WebAuthn passkeys after a normal password login.
Passkeys are user-owned public credentials, not super-admin credentials. The app
stores only the public credential ID, public key, signature counter, and safe
device metadata; the private key and local unlock method stay on the user's
device or passkey provider. Passkey registration and login must use one-time
session challenges, require CSRF on browser fetches, require user verification,
verify the configured relying-party ID and origin, update signature counters on
successful login, block disabled users, audit only safe metadata, and keep
password login available as fallback.
`/config` is the persistent passkey management surface. User-facing buttons and
prompts should call this **Device sign-in** so users understand it can use a
phone, browser, biometric unlock, PIN, or another passkey-capable device.
The login page shows the normal username/password form first and places the
Device sign-in button under the password sign-in button as the alternate
managed-user login path.
`/work` may show a device sign-in setup card only once after each successful
login, only on phone-sized layouts, and only while that managed user has no
registered passkeys.

Managed web users may change per-login configuration on `/config`. Per-user
configuration is database-backed, defaults to Default Dark with Teal
highlighting, saves immediately when an option changes, and supports eight
independent background profiles plus ten named highlight colors for
authenticated mobile and web pages. Highlight colors must use contrast-adjusted
light and dark shades while preserving the selected color family. It also
supports the default-off **Submit
from Work in Progress** option. When enabled, ending an active job submits the
time entry directly to Autotask instead of stopping in Review first. The
per-user navigation setting supports None, Device Default, Google Maps, Waze,
and Apple Maps. Home address is required only while navigation is enabled.
Office address is optional and overrides `NAVIGATION_OFFICE_ADDRESS` when set.
Navigation buttons and automatic On-Site service-call directions are mobile-only
by default. Phones, tablets, iPads, and iPods count as mobile independently of
viewport width. **Allow navigation on full web version** is a separate
default-off per-user preference; disable and grey out that checkbox while
Navigation is None. Full-browser navigation requires both a configured
navigation app and this explicit opt-in.
**Hide Home and Office navigation buttons** is a separate default-off per-user
preference that hides only those two quick destinations on Work. Disable and
grey it out while Navigation is None, and never use it to hide ticket or
service-call destination navigation.
**Automatically open On-Site directions** is a separate default-on per-user
preference. When it is off, starting an On-Site service call must create the
job without requesting a navigation launch; the ticket destination navigation
button remains available. Disable and grey out this checkbox while Navigation
is None.
For every future feature that must distinguish a mobile device from the full
web version, reuse `window.TicketPilotNavigation.isMobileDevice()` from
`ticket_pilot/static/navigation.js`; use
`window.TicketPilotNavigation.isNavigationAllowed()` when the full-web navigation
preference also applies. Do not add feature-specific viewport-width, user-agent,
or touch checks elsewhere. Extend the shared detector and
`tests/test_navigation_javascript.py` when another device case must be covered.
This classification controls presentation and convenience behavior only and
must never replace server-side authentication, authorization, or validation.
Keep home and office addresses out of audit events and logs. Autotask customer
addresses are transient provider data and must not be stored on Job rows. The
password-change section on `/config` is the exception: it requires two matching
password entries and an explicit **Change password** submit button, and the
password card must show the managed-user password requirements. The config
super admin does not have user settings, does not see the Config menu item,
cannot access `/config`, and always renders in Default Dark.
The `/config` cards should render in this order: **Appearance**, **Password**,
**Navigation**, **Workflow**, then **Device sign-in** as the final card.

Never rely on the mobile UI, browser state, or hidden form fields for security
decisions. The server must validate authentication, authorization, CSRF tokens,
job ownership, workflow status, timestamps, ticket numbers, ticket statuses,
project IDs, project-task IDs, task statuses, and all submitted text.

Store all secrets outside source control. Autotask credentials, transcription
provider credentials, session secrets, database passwords, Cloudflare Tunnel
tokens, SMTP passwords, SMTP2GO API keys, Turnstile secrets, and API keys must
come from environment variables, Docker secrets, or another approved secret
store.

Do not log secrets, session tokens, raw authentication headers, Cloudflare Access
JWTs, Autotask API credentials, transcription provider credentials, raw audio,
or other sensitive values. Successful and failed app-login attempts must be
stored in the database as sanitized `login_attempts` records and shown on
`/diagnostics` only with safe metadata such as timestamp, client IP, submitted
username, account kind, authentication method, user agent, request/proxy
details, failure reason, and password-present/length for failures. Never store,
write, or display the raw submitted password. For login diagnostics, display the
sanitized proxy client IP provided by nginx while retaining the direct socket
peer and proxy headers as supporting metadata. Do not use display-only request
headers as authorization or blocking decisions. Local login lockout and
automatic Cloudflare blocking must use the trusted enforcement IP from
nginx-sanitized `X-Real-IP`/`X-Forwarded-For` or, outside the bundled proxy
path, the direct socket peer. The failed-login table may hide individual rows by
setting `login_attempts.hidden_at_utc`; JSONL downloads are generated from the
database for diagnostics and must remain sanitized. Cloudflare IP blocking on
`/diagnostics` may create or remove only app-managed zone IP Access Rules tracked in
`cloudflare_ip_blocks`; it must honor `CLOUDFLARE_IP_BLOCK_ALLOWLIST`, use the
trusted enforcement IP, store a safe reason for every block, and reset
`login_failure_counters` to zero after a successful local login for the same
enforcement IP and submitted username. The Diagnostics Cloudflare controls may
block an IP from a failed-login row or from a manual IP entry, but both paths
must require CSRF, normalize the IP, honor the allowlist, and submit only the
app-managed rule note to Cloudflare. After
`CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS` consecutive failures, local
password and Device sign-in verification must be blocked for
`LOGIN_LOCAL_LOCKOUT_MINUTES`, defaulting to 15. The successful-login window
may visually distinguish config
super-admin account-kind chips from managed web-user chips, but must not expose
extra sensitive metadata to do so. It may also show the safe successful-login
authentication method as `Password` or `Passkey` status pills. Successful-login,
login-failure, and Autotask submission-attempt diagnostics must stay paginated
at 7 rows per page without vertical table scrollbars. Cloudflare blocked-IP
diagnostics stay paginated at 10 rows per page.

Prefer secure defaults. Cookies must be HTTP-only, secure when served over HTTPS,
and SameSite-protected. Forms and state-changing requests must use CSRF
protection.

The application must maintain immutable audit events for important actions,
including job start, job end, description recording, transcription updates,
manual workflow edits, review decisions, direct Work in Progress Autotask
submission, Autotask submission attempts, Autotask submission success, Autotask
submission failure, password reset events, and authentication-sensitive events.
Browser summary-note autosaves through `/jobs/{job_id}/description/text` must not record
`job.description.browser_text_saved` or appear in the Review audit timeline.
Review autosaves must not record `job.review.saved`, and legacy
`job.review.saved` rows must also stay hidden from the Review audit timeline.
Successful Autotask submissions must record a visible `job.autotask.submitted`
activity.

Raw audio must not be stored by default. If audio retention is ever added, it
must be explicit, configurable, documented, access-controlled, and auditable.

AI summary cleanup sends job summary text to the configured provider only when
`AI_CLEANUP_ENABLED=true` and `AI_CLEANUP_PROVIDER` is `gemini`, `grok`,
`ollama`, or `lm_studio`. Treat summary text as customer/work data. The server
must validate authentication and CSRF, bound input length, keep API keys,
provider URLs, and cleanup instructions server-side in Docker or environment
variables, constrain Ollama and LM Studio cleanup URLs to loopback or
private-network endpoints, send
`AI_CLEANUP_INSTRUCTIONS` through the provider instruction field, and audit
only metadata such as provider, model, source, and text lengths. Gemini cleanup
uses the same OpenAI-compatible `GEMINI_API_BASE` endpoint setting as AI Help
while keeping `GEMINI_CLEANUP_MODEL` separate from the Help model and
`AI_CLEANUP_INSTRUCTIONS` separate from `AI_HELP_INSTRUCTIONS`. Do not store
raw cleanup prompts or full cleaned/uncleaned summaries in audit details.
After a successful cleanup, the UI may store the pre-cleanup summary on the job
only for the explicit **Revert cleanup** workflow. That stored customer/work
text must not be copied into audit details or diagnostics, and it should be
cleared when the user reverts cleanup or the cleaned notes are successfully
finalized in Autotask. Stale cleanup undo text must also be cleared after
`AI_CLEANUP_REVERT_RETENTION_HOURS`, defaulting to 24 hours, so the app does
not retain extra customer/work text indefinitely.

The Help assistant sends authenticated end-user support questions and bounded
local documentation/source context to Gemini only when
`AI_HELP_ENABLED=true`, `AI_HELP_PROVIDER=gemini`, `GEMINI_API_KEY`, and
`AI_HELP_INSTRUCTIONS` are configured server-side. Treat help questions, help
instructions, and source context as sensitive. The server must validate
authentication and CSRF, bound question, instruction, and context size, keep API
keys and private deployment details out of source control, avoid local database
storage of prompts and answers, and refuse source-code, deployment, secret,
credential, or internal configuration questions. `GEMINI_API_BASE` is the
OpenAI-compatible Gemini base URL; the app may accept a full
`.../chat/completions` endpoint for operator recovery, but it must build the
final endpoint once and never append that path twice. The assistant is for
end-user TicketPilot support only. Built-in Help instructions should favor
concise complete answers, and server-side answer cleanup may remove short
dangling trailing fragments after a complete sentence. The Help page may show a
general operational-status card to all authenticated users, but specific health
issue labels and summaries must be visible only to Diagnostics-authorized
users. AI Help troubleshooting logs may include sanitized metadata such as trace
ID, provider, model, HTTP status, error class, input and answer lengths, context
source count, and timing, but must not log Gemini API keys, full questions,
prompts, source context, provider request bodies, or answers. When
`ADMIN_CONTACT_EMAIL` is configured, successful AI Help answers should append
`If you need further help, contact <admin email>` under the answer with a blank
line between the AI answer and the contact line.

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
5. The review page allows the entry type, time, status, and notes to be edited before
   acceptance while keeping the selected Autotask client and ticket or project
   task read-only.
   Client identity must come from a selected Autotask company search result;
   typed names that do not match the verified selected company ID must be
   rejected and not saved.
   Work in Progress may replace a verified client/company selection while no
   work target has been chosen yet, so the user can search another client and
   load that client's open tickets and assigned project tasks. Once a ticket or
   project task is chosen for the job, client identity is read-only. If an
   active job is opened in Review before
   any client has been selected, Review detail may save the first
   client/company through the authenticated Autotask company search; after that
   Review selection, client identity is read-only on Review.
6. An accepted review job, or a directly submitted Work in Progress job,
   creates an Autotask time entry or a note on the selected target. Ticket
   targets use `TicketNotes`; project-task targets use `TaskNotes` and must
   never create `ProjectNotes`. The local entry type is editable only before
   successful Autotask submission. Ticket notes and project-task notes require
   the selected target's status, note title, note description, and verified
   target identity; they do not require start/stop times or Remote/On-Site work
   location. Time entries keep the existing date, start time, end time, summary
   notes, work location, and target-status requirements. Time entries expose
   **Append to resolution**, defaulting on, and send that setting to Autotask.
   Autotask TicketNotes and TaskNotes do not support
   `appendToResolution`; do not show or send that field for either note type.
7. A successfully submitted Autotask job keeps target and client identity
   read-only. The entry type cannot be changed after successful submission.
   Time entries can change job date, start time, end time, summary notes, work
   location, append-to-resolution, and ticket or task status only through the audited
   **Submit changes** action, which updates the existing `TimeEntries` row
   instead of creating another entry. Notes can change note title, note
   description, and target status through the same audited action, which
   updates the existing `TicketNotes` or `TaskNotes` row. **Submit changes**
   patches `Tickets.status` for ticket work or `Tasks.status` for project-task
   work. When needed, it may temporarily move a previously Complete ticket or
   project task to In progress before patching the external record, then move
   only that target to the selected final status after the record patch. Never
   patch `Projects.status` as part of task work. The audited **Delete From
   Autotask** action may delete an
   external `TimeEntries` record and move the local job back to review, but must not
   delete the local job record. If Delete From Autotask fails, the selected
   review detail may show an explicit local-only purge fallback that removes
   the TicketPilot review row while warning that the Autotask record may still
   exist.
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
Work in Progress and Review detail must show the rounded start-to-stop duration
using labels such as `Work Duration: 15 Minutes`, `Work Duration: 1 Hour`, or
`Work Duration: 1.25 Hours`, and must update the value as the visible rounded
times change. Work in Progress and Review detail show the centered **Work
Duration** row under the start/end time controls so full-browser start and end
fields stay aligned.
Ticket-note mode hides this duration because start and stop times are not used
for Autotask ticket notes.
Time-entry duration validation must enforce the work-location minimum:
Remote work requires at least 15 rounded minutes, and On-Site work requires at
least 1 rounded hour. Apply the same server-side rule to active end-work,
Review saves, Review submission/retry, submitted-entry edits, and direct
Work in Progress Autotask submission. Ticket notes are exempt because they do
not use start/stop time fields.
On active Work only, selecting Remote or On-Site must recalculate only the stop
time. Use the later of the selected location minimum or the current rounded
15-minute block, keep the start unchanged, persist the canonical stop, and
return it to the browser so Work Duration updates immediately. Review and
submitted-entry edits remain manual and must continue to reject durations below
the selected work-location minimum.

Jobs do not span multiple work dates. Review forms must use one local job date
with start and end times, and must reject edits where the end time is not after
the start time on that same date.

Rounding behavior must be centralized in one tested time utility instead of
being duplicated across routes, templates, or Autotask integration code.

Daylight Saving Time edge cases must be considered when converting local times.

## Autotask Integration

Autotask records are created after review acceptance by default. A managed web
user can opt in to direct Work in Progress submission on `/config`, which
creates the selected Autotask time entry, ticket note, or project-task note
during end-work after the same local submission requirements pass.

The required Autotask time-entry fields for this application are:

- Verified ticket or project-task identity.
- Summary notes.
- Local ticket or task status selection.
- Date.
- Start time.
- End time.

The required Autotask ticket-note fields for this application are:

- Ticket number.
- Ticket status.
- Note title.
- Note description.

The required Autotask project-task-note fields are:

- Project-task ID and parent project ID.
- Task status selected from current tenant `Tasks.status` metadata.
- Note title.
- Note description.

Ticket notes created by TicketPilot must be customer-visible, never internal.
Time entries include the local **Append to resolution** setting in the Autotask
payload. Ticket notes and project-task notes must omit the unsupported
`appendToResolution` field. Project-task note mode must create and update
`TaskNotes` through the selected task's child endpoint; never use
`ProjectNotes`.

Supported ticket status values are:

- In progress.
- Waiting customer.
- Waiting parts.
- Mfg Trouble Ticket.
- Follow up.
- Complete.

`AUTOTASK_STATUS_NEW_ID` and
`AUTOTASK_STATUS_CUSTOMER_NOTE_ADDED_ID` are read-only recognition mappings,
not selectable local statuses. Never add **New** or **Customer Note Added** to
the user ticket-status dropdown. Compare the server-verified numeric Autotask
status ID with the configured mapping. When a user selects a **Customer Note
Added** ticket from Work or Review, or starts it from a service call, request
the existing Ticket notes overlay once with the newest note selected. Closing
the overlay or reloading must not reopen it. Service-call navigation may carry
only the new local job ID through same-tab session storage; browser state is
presentation-only and the authenticated, owner-checked ticket-notes endpoint
remains authoritative.
Open-ticket and service-call options with at least one displayable customer
note should show the shared **Note** indicator in the active highlight's
complementary counterpart color. The selected Ticket name card must show the
same indicator, and the **Ticket notes** button must use the same counterpart
treatment plus that indicator while notes exist. Note
availability must come from server-side Autotask lookups and apply the same
system-note exclusions as the authenticated overlay; browser code must never
query Autotask directly.

The selected-company work picker must return separate **Tickets** and
**Project tasks** groups. After options load, the **Open Tickets (N)** panel
heading shows their combined count. Do not repeat that count in a separate
success message or show a redundant project-task helper sentence. Project-task
options come only from non-complete
tasks on non-complete, non-inactive, non-template, non-baseline projects for the
verified company, and only when the logged-in managed user's Autotask resource
is the task's primary or secondary resource. Use the documented
`Projects.projectType` picklist and record field to exclude Template and
Baseline projects when the tenant permits that metadata. Some tenant/API-user
security combinations return a misleading HTTP 500 when `projectType` metadata
or fields are queried. Treat project type as optional in that case: retry the
Project query without `projectType`, retain project-status, task-status, and
resource-assignment filtering, and do not block the ticket results. Without the
field, Template and Baseline projects cannot be pre-filtered. If the core
Project query is also denied, treat assigned project-task discovery as
unavailable for that request: return the independently verified ticket results,
an empty Project tasks list, no task-status options, and a bounded Projects
permission warning. Never let a Projects permission failure discard valid
ticket choices. Autotask does not
expose a task-level allow-time-entry flag; actual time-entry authority remains
governed by the resource's Autotask Projects security permission. Store the verified
task ID, parent project ID, display metadata, and current task status locally,
then keep that target identity read-only. Task-status choices must be read from
the tenant's active `Tasks.status` picklist metadata and rendered in the same
position as Ticket status under the label **Task status**. Never substitute the
parent project's status.

Service-call lookup must support both `ServiceCallTickets` /
`ServiceCallTicketResources` and `ServiceCallTasks` /
`ServiceCallTaskResources`. If one service call has both associations, return
one clearly labeled selection card for each verified association. Starting a
project-task service call must store the verified task and parent-project
identity and must not patch either status before submission.

Autotask submission must be idempotent. A retry must not create duplicate
TimeEntries, TicketNotes, or TaskNotes rows for the same accepted job.
Before any Complete-status create or submitted-entry update, globally check all
local owners for another entry with the same normalized ticket number or
project-task ID in Active, Ready for Review, or Submission Failed state. Block
the Complete submission until every such time entry or note has submitted, so
the Complete entry always reaches Autotask last. For a project task, create or
patch `TimeEntries` or `TaskNotes` first and only then set `Tasks.status` to
Autotask's documented Complete value `5`. Never complete the parent project.

Autotask resource IDs are not global configuration. They belong to managed web
users and are required before a user can start work. The app uses the logged-in
or owning user's resource ID for service-call lookup and for
`TimeEntries.resourceID` on create. User-scoped Autotask calls must not send
Autotask's optional `ImpersonationResourceId` header; do not add or restore a
global `AUTOTASK_IMPERSONATION_RESOURCE_ID` setting. Static Autotask role and
billing-code IDs must not be configured. Ticket-target submission and submitted
**Submit changes** actions must patch `Tickets.status` to the selected local app
ticket status, using the configured tenant-specific `AUTOTASK_STATUS_*_ID`
mapping. Project-task work instead uses current tenant task-status metadata and
patches only `Tasks.status` through its `Projects/{projectID}/Tasks` child
endpoint. The live provider must query the selected ticket at
submission time, use `Tickets.assignedResourceroleID` as `TimeEntries.roleID`
when available, fall back to
`TicketSecondaryResources.roleID` for the submitting managed user's resource
when that user is a secondary resource on the ticket, then fall back to
`Tickets.assignedResourceID` to resolve that resource's default or single active
`ResourceServiceDeskRoles.roleID`, then use the submitting managed user's
configured default service-desk role ID when present, then fall back to the
submitting managed user's default or single active service-desk role when the
ticket omits assigned role context. The app must still send the submitting
managed user's resource ID as `TimeEntries.resourceID`. Omit
`TimeEntries.billingCodeID` so Autotask inherits the selected ticket's Work Type
on create. API credentials, tenant ticket status IDs, time-entry type, and
optional Autotask provider settings remain environment configuration.
The super-admin `/users` page may query `/Resources/query` through the server
to find matching Autotask Resources by `Last, First` name and fill the
user-specific resource ID and optional email address. It may also query
`ResourceServiceDeskRoles` through the server to list active role IDs for the
selected resource, enrich those dropdown choices with `Roles.name` when allowed,
and save the chosen numeric per-user fallback role ID.
For project-task time entries, send `taskID`, `timeEntryType=6`, the submitting
managed user's `resourceID`, and that user's unambiguous primary-task or
`TaskSecondaryResources.roleID`. Do not send `ticketID` for task work.
Selected-target notes and past time entries are read-only Autotask context.
Work in Progress and Review detail may show **Ticket notes** or **Project task
notes** only when the authenticated server route confirms that bounded notes
exist for the selected target. They may also show **Past time entries** when
the authenticated route confirms bounded `TimeEntries` rows exist for that
ticket or task. Do not call Autotask directly from browser JavaScript or expose
raw provider responses. Resource names returned by Autotask for authenticated
display must be shown first-name first, even when Autotask stores or returns
the combined name as `Last, First`.

Autotask API errors must be recorded clearly for review and troubleshooting
without exposing credentials or sensitive protocol details. Any failed live
Autotask API request from any managed user, managed Admin user, or config
super admin must mark cached app health degraded for that semantic operation
type. The authenticated top-bar degraded icon must remain visible until the same
operation type succeeds again; unrelated successful Autotask requests must not
clear a different active failure.
Live Autotask REST calls must also pass through the shared provider request
wrapper so `AUTOTASK_MAX_CONCURRENT_REQUESTS`, defaulting to 2 and validated
from 1 through 3, can keep TicketPilot below Autotask's three-thread threshold.
PostgreSQL-backed deployments coordinate that limiter across app processes
sharing the same database by using advisory locks; deployments that do not
share a database are still independently capped by their own process-local
limiter and should keep lower per-instance limits when they share the same
Autotask tenant or API user.

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
summary field. Audio, AI Cleanup, and save status messages share one plain-text
status line. The spinning loading icon belongs in the active button itself,
such as the disabled active-job **Record** button while the recording is still
being sent or converted and the **AI Cleanup** button while cleanup is running.

The local faster-whisper provider may use `FASTER_WHISPER_INITIAL_PROMPT` to
guide transcript formatting, including rendering dictated punctuation words as
punctuation marks. Treat it as a best-effort model hint, not a validation or
security control.
`TRANSCRIPTION_PROVIDER=faster_whisper_remote` may call a trusted remote
faster-whisper API while preserving the local `faster_whisper` option. Remote
transcription sends raw audio to the configured server, so HTTP endpoints must
stay on loopback or private-network hosts and public endpoints must use HTTPS.
Keep the remote URL and optional bearer token in environment or Docker secrets,
never in source control or templates.

AI summary cleanup is separate from speech-to-text. It sends the current
editable summary text to the configured server-side cleanup provider and
replaces the summary textarea with the returned cleaned text. It must not
submit to Autotask or bypass the configured finish/review workflow.
After a successful cleanup, Work in Progress and Review switch the button to
**Revert cleanup** while stored undo text exists. Revert restores the
pre-cleanup editable notes and clears that undo state. Submitted Review entries
may keep a pending cleaned draft across reloads, but Autotask must still be
patched only by the explicit **Submit changes** action. Expired cleanup undo
state should be cleared opportunistically before rendering or acting on those
surfaces.

The review page must allow the transcribed description to be edited or
re-recorded before the job is accepted and submitted to Autotask.

Do not permanently store raw audio by default.

## Web Interface Requirements

The mobile interface must be optimized for quick use from a phone.
Mobile summary notes textareas should default to a taller note-taking area than
the shared desktop textarea baseline while remaining vertically resizable.

The `/work` route is canonical for the Home and Work in Progress workflow.
`/home` remains a backward-compatible redirect to `/work`, and old
`/home/service-calls` requests remain accepted while new browser requests use
`/work/service-calls`. Full browser
rendering should use desktop-only CSS from `desktop.css` for a wider,
scan-friendly layout. Keep full-browser layout changes out of `phone.css` so
the installed mobile phone experience remains unchanged unless explicitly
requested. Do not use route names to select the mobile or desktop page version;
presentation must follow client/browser and media behavior. Full-browser
and mobile workflows should advance keyboard focus to the next natural input:
blank Start Work focuses the new job's verified company search, while ticket,
project-task, and service-call selection focuses that same job's summary field.
Reload handoffs must be one-time and job-specific so concurrent jobs do not
steal focus from each other or refocus after a later manual reload. Full-browser
start-work panels should keep the **Service calls** heading visually raised
above the date selector while the date selector and service-call list stay
tightly stacked without a divider line above the section.
Both the blank and one-active-job concurrent start panels must use this same
full-browser two-column treatment: a smaller single-line title and Start Work
control on the left, with Service calls on the right. The Help page must begin
with its first card without a redundant Support/Help page heading. Config must
begin with the compact **User Settings for &lt;full name&gt;
(&lt;username&gt;)** line, omit a separate Config heading, use the full desktop
content width, and retain one-card-per-row stacking on phones. On full-browser
Config, keep Password with Workflow in the left column and Navigation with
Device sign-in in the right column so Workflow sits directly below Password
without inheriting Navigation's taller card height. The phone card order remains
Appearance, Password, Navigation, Workflow, then Device sign-in.
When no service calls are available for a selected day, the full-browser
empty-state message should be centered. Phone spacing should remain governed by
the shared/mobile CSS.
When two active jobs are present, their Work in Progress cards should use
distinct slot shading so they are easier to tell apart, and the most recently
started job must appear above the earlier active job. On full-browser Work in
Progress cards, the End Work/Delete row belongs directly under the
Record/AI Cleanup row, and recording/AI status text belongs below all action
buttons. Active Work in Progress cards should show an editable **Job date**
calendar field instead of the raw started timestamp, with `(Today)`,
`(Yesterday)`, or `(Tomorrow)` shown inside the date selector box when the
selected date is adjacent to the current app-local date. The date and relative
label should be centered together with two spaces between them, such as
`06/29/2026  (Yesterday)`. Other selected dates show only the centered date.
The selected local date must be saved server-side through the active-job
workflow and carry into Review and Autotask submission. The selected Review
detail **Job date** field should use the same centered in-selector treatment.
All app date chooser fields should use the shared app-controlled calendar with
**Today**, **Cancel**, and **Set** controls instead of relying on native browser
picker wording.
The active **Start time** and **End time** fields should use the same 12-hour
editable time-field treatment as Review detail start/end times, keep the `-15`
and `+15` controls, open a 15-minute dropdown centered on the current field
value when selected, and save only through server-validated active-job routes.
Work in Progress and Review detail should center the rounded-duration label in
the existing time area without reworking the mobile or full-browser layout, and
the visible label should read **Work Duration**.
On full-browser Work in Progress and Review detail cards, the editable workflow
cards should appear as equal-width paired rows: **Entry type** with **Work
type**, **Job date** with **Ticket status**, **Start time** with **End time**,
then the centered **Work Duration** row under the time row. Full-width Review detail rows
that do not share a row with another card should stay full width. Full-browser
Review detail should keep **Client name** and **Ticket number** together as the
paired row above a full-width centered **Ticket name** card, then show
**Ticket description** below the ticket-name card. The Review **Ticket notes**
and **Past time entries** buttons belong at the bottom of the **Ticket name**
card. Full-browser Work in Progress cards should place **Client name** and
**Ticket number** together on the next row when a ticket number is shown, then
place **Ticket name** full width below that row with the desktop **Ticket
notes** and **Past time entries** buttons under the ticket name. Full-browser
Work in Progress left-side context cards should use equal half-width card
slots, except **Ticket name** and **Ticket description**, which remain full
width. Phone-sized Work in Progress should center the display-only **Client
name** and **Ticket name** card titles and values when a ticket has been
selected.
Active Work in Progress cards should keep a visible **Work in Progress** label
above the selected ticket heading on phone layouts. Full-browser active cards
should also use that heading row for the selected ticket name even though the
centered **Ticket name** card repeats the same value. The full-browser layout
depends on that label row so the Summary notes panel starts flush with the top
of the **Job date** card; keep that label prominent enough to read quickly.

Managed web-user pages must respect the current user's saved background and
highlight preferences. Default Dark with Teal is the initial appearance.
Config exposes Default Light, Sage Light, Sky Light, Default Dark, Midnight
Black, Graphite Dark, Forest Dark, and Plum Dark as three light and five dark
background profiles in a dropdown whose selected value and every option show
three round swatches for that background's page, surface, and muted-surface
colors. It separately exposes Teal, Sage, Sky Blue, Blue, Indigo, Amber,
Orange, Mint, Lavender, and Rose in a dropdown with a visible color sample for
every option. Midnight Black replaces Slate Dark, and migrations must preserve
the effective highlight of older saved themes and backups.
Every background/highlight combination must cover mobile, review, user
management, Config, Diagnostics, and login surfaces through shared CSS
variables instead of separate unaudited template branches. Super-admin pages
always use Default Dark with Teal. `docs/design/theme_palettes.svg` is the
maintained reference for all eight backgrounds and ten highlight/counterpart
pairs. Navigation icons, ordinary buttons, Remote choices, and Time entry
choices use the active highlight color. Every highlight also defines an
automatic complementary counterpart with contrast-adjusted light/dark shades.
Use that counterpart for On-Site choices and option-card outlines, Ticket note
choices, customer-note indicators and button emphasis, recording controls, and
the second concurrent-job accent. Established destructive, success, genuine
warning, AI, status, and disabled-control colors retain their semantic meaning.
When Docker/runtime `DEV_BUILD=true`, authenticated desktop and mobile headers
must mark the Help navigation button in yellow so dev instances are visually
distinct from production without adding a separate pill. Full-browser
authenticated headers also show the version under the left-side TicketPilot
title, using `vX.Y.Z-DEV` for dev builds. The Help page itself must show the
current version with `DEV`, such as `v2.1.0 DEV`.

On phone-sized authenticated layouts, the top bar hides the brand mark and the
desktop logout control. It shows compact route and status icons on the left,
with Work and Review left-aligned for managed web users. Help, Config,
optional Diagnostics, and logout are right-aligned in that order. The Work
button links to `/work` and uses the same work-entry icon on phone and
full-browser navigation. The shared authenticated top bar must remain visible
at the top of the viewport while any phone or full-browser page scrolls through
its complete document. The config super admin sees Users and Review on the
left, with Help, Diagnostics, and logout on the right, and must not see the
Config shortcut.
The mobile logout button must post to `/logout` with the
rendered CSRF token and
must not use `window.close()` or a browser-only app close fallback. Full-width
`/work`, Review, Diagnostics, and other non-mobile authenticated views still expose
the explicit desktop logout control. Full-browser route navigation should be
centered, use raised blue icon-and-text buttons, place Help immediately before
the right-side **Log out** button. The authenticated desktop brand mark and
favicon must use `ticketpilot-logo-white.svg` for all dark themes and
`ticketpilot-logo-black.svg` for all light themes, with
`ticketpilot-logo-grey.svg` as the neutral fallback. Config theme changes must
update both without a page reload. The PWA manifest must advertise the maintained
`ticketpilot-app-icon-*` PNG sources at 128, 256, 512, and 1024 pixels, and the
Apple touch icon must use the 256 pixel source. Do not advertise maskable
install icons unless a future design includes separately supplied and tested
full-bleed mask-safe artwork. It should include a **Log out**
button with the logout icon and visible text while preserving the phone-sized
icon navigation. Phone top-bar navigation buttons should use the same blue
visual treatment as the full-browser navigation buttons, and all phone nav
icons should use one shared visible size inside their compact buttons.
Enabled buttons and button-like navigation controls should show a slight
brighter hover state, and workflow action buttons should have a raised idle
state plus a pressed-in active state. Destructive red controls should stay red
on hover and use a brighter red treatment, not a neutral or black hover.
When cached application health is degraded, every authenticated user sees a
top-bar exclamation status button that links to `/help#operational-status`.
The button must use the app-health severity color, yellow for warning and red
for critical, and must not expose diagnostic details to ordinary managed users.
The Help page **Operational Status** card uses the same severity colors and
also shows green when all monitored checks are operational. The desktop icon
sits in a reserved header status area between primary navigation and the
right-side Help/logout actions; the phone icon joins the compact left-side
route group so Help can stay immediately beside logout. Do not run live
Autotask probes while rendering a page.
The unauthenticated login page should not show a top app icon or wordmark above
the sign-in form. It must use its own neutral black, white, and grey palette,
including controls, focus states, and feedback messages, without inheriting or
applying any authenticated background or highlight theme.

The standard review interface must work well on a full computer screen.

The review interface must allow editing of reviewed entry type before
successful Autotask submission, job summary notes or note description, ticket
status, date, start time, end time, work location, and the translated
speech-to-text description before acceptance. The review list must show each
job's Remote or On-Site mode for time entries and Ticket note for note-mode
entries, paginate newest-first at 10 jobs per page, and include day-hours and
week-hours totals calculated from time-entry jobs for that job's owner, local
job date, and local work week. Ticket notes do not contribute to hour totals.
The Work page and Review page should also show time-entry hours worked today
and this week, including `0 Hours` when no time-entry work has been recorded.
Work should show those values as a centered, compact, discreet boxed summary
rather than full metric cards. On full-browser Work, that summary should begin
close below the navigation bar without the larger generic page-shell top gap.
Review must omit the page title and description so its Today, Week, and
Unsubmitted cards begin just below the navigation bar. On full-browser Review,
the job list begins at the top of the left column, flush with the three-card
summary row at the top of the right column. The summary should match the width
and right edge of the Review detail card below it, with three equal-width cards.
Persist each user's **Hide submitted entries** filter and page size choice of
10, 20, 50, or 100. Use 20 as the first full-web default and 10 as the first
mobile default through the shared navigation device detector. Pagination must
include First, Previous, Next, and Last controls.
On phones those three same-sized cards must fit on one row and use abbreviated
duration values such as `15m`, `1h`, or `1.25h`; full-browser cards retain the
complete duration labels. Unsubmitted counts only time-entry jobs in Active,
Ready for Review, or Submission Failed status; ticket notes, rejected jobs,
and successfully submitted jobs do not count.
Managed users see only their own count, while the config super admin sees the
count across all owners in the same review scope. The summary
textarea for time entries must show the complete Autotask summary that will be
sent, including the leading `Remote. ` or `On-Site. ` prefix. Saving review
edits parses that prefix back into the stored
`work_location` field, and the review-detail work-location control must update
that visible prefix, so the final payload can be corrected without exposing
ticket or client identity to edits. Ticket-note mode keeps the Work type
Remote/On-Site card visible but disabled and greyed out, changes the date label
from **Job date** to **Note Date**, hides start/end time controls while
preserving their values for switching back to Time entry, shows a required
left-aligned note-title input above the note description, and keeps the description
unprefixed. Shared switch pills should show Time entry and Remote selected
states in the active highlight color, and Ticket note and On-Site selected
states in that highlight's complementary counterpart color.
On phone-sized Work in Progress and Review detail layouts, the editable
workflow cards should appear in this order: **Entry type**, **Work type**,
**Ticket status**, **Job date** or **Note Date**, **Start time**, **End time**,
then **Work Duration**.
**Append to resolution** should sit under time-entry summary notes and above
the action buttons, but must be hidden in ticket-note mode. The
selected Autotask
client name, company ID, ticket number, and ticket title are read-only identity
fields populated from Autotask lookup and must not be editable on the review
page. The only exception is the empty-identity active-job case, where Review
detail may expose Autotask company search to save the first verified
client/company before ticket lookup.
Review client searching must not run the generic review autosave or show
summary-note validation while the user is typing a client; an empty summary
warning should appear only when AI Cleanup is pressed without notes or when the
user submits a workflow action that requires summary notes.
On Work in Progress, a verified client may be changed while no ticket is
selected yet. Once an open ticket has been chosen, the stored client name
becomes read-only everywhere for that job.
Open-ticket and service-call choices should receive only a safe
`has_customer_notes` boolean derived from a batched, bounded server-side
TicketNotes lookup. Treat this indicator lookup as optional context: a
TicketNotes permission or transient failure must not block the primary ticket
or service-call workflow.
When a selected Autotask ticket exists, Work in Progress and Review detail
should run authenticated lookups for ticket notes and past time entries near
the ticket context. Before a ticket is selected, keep the buttons hidden. After
lookup, expose compact **Ticket notes** and **Past time entries** buttons when
rows exist; when no displayable notes or no past time entries exist, show
same-place disabled **No Notes** and **No past entries** buttons. On
phone-sized layouts, Work in Progress places those buttons under the centered
**Ticket name** card, and Review places a centered **Client name** card
directly above the centered **Ticket number** card, then a centered **Ticket
name** card with the **Ticket notes** and **Past time entries** buttons split
across one row above **Ticket description**. On phone-sized layouts, both
ticket-history buttons must open the same full-screen overlay. Work in
Progress and Review must place **Navigate to Destination** on its own full-width phone row
immediately above the **Entry type** pill card. Show that phone row only for
time entries; ticket-note mode must hide it even when a destination is
available. Home, Office, and Navigate to Destination controls should use the
shared subtle blue navigation-button treatment. Work in
Progress must keep the **Past time entries** button visible beside **Ticket
notes** for every active job whose authenticated lookup returns rows,
including the first active-job card when two jobs are open. On full-browser
Review, the
**Client name** and **Ticket number** cards sit together above a centered
**Ticket name** card, and the **Ticket notes** and **Past time entries**
buttons sit at the bottom of that ticket-name card directly above **Ticket
description**. Ticket-note
lookups must filter out Service Desk Notification notes, notes whose title
starts with Workflow Rule, and Autotask action-status notes whose title starts
with Some actions did not occur before deciding whether any notes exist. The
shared overlay must keep an X
close button visible while the user reviews the list and detail panes. The note
list should be ordered by created date/time with the newest note first, and
selection cards should show only the note title so note body text cannot
overflow the cards. Selection cards should fit two lines of note title text and
truncate longer titles inside the card. Note detail metadata should include who
the note was from when Autotask returns a safe author reference. Past
time-entry selection cards should show the resource name first-name first and
formatted local start/stop/hours text on one larger single-line row, and the
selected detail should show a larger date/time row plus the summary of work.
Work in Progress and review detail action controls should stay compact and
scannable on both phone and full browser layouts. Use paired button rows when
two actions naturally belong together, such as **Record** with **AI Cleanup**,
**End Work** with **Delete**, and review submit/edit actions with the matching
delete action. Never place more than two action buttons in one row. Work in
Progress and Review detail should use one shared status line directly below the
visible action-button group for **Changes saved**, recording, and AI Cleanup
messages; the newest message should replace the previous status instead of
adding another line.
Status chips across review, diagnostics, and user management should use the
shared outlined, all-caps pill treatment while preserving status-specific
colors.

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
Docker Compose Nginx host publishing must bind only to `127.0.0.1` and use
`HTTP_PORT` for the host-networked Cloudflare Tunnel origin URL, such as
`http://127.0.0.1:2082`. Swarm keeps the Nginx listener private to its overlay.
The internet-facing nginx template must block public API-style, generated docs,
and public health paths and use app-styled TicketPilot web service error pages
for common nginx-generated 4xx and 5xx responses instead of stock server pages.
Browser navigation to app-generated HTTP errors, including missing FastAPI
routes, must also render app-styled TicketPilot error pages. Those pages should
show **Back to Login** when there is no valid app session and **Back to Work**
when the request already has a valid authenticated session, while API-style
clients that request JSON should keep receiving JSON error bodies.
Compose must fail closed when `APP_SECRET_KEY`, `APP_PASSWORD`, or the selected
database credential source is missing instead of falling back to development
secrets. Local-db deployments use `POSTGRES_PASSWORD`; remote database
deployments use `DATABASE_URL`.
Compose and Swarm must default the optional Cloudflare Access header gate off.
Operators may set `CLOUDFLARE_ACCESS_REQUIRED=true` only after a matching
Cloudflare Access application is configured. Production startup must only hard-require secure session
cookies, non-default app/database secrets that are not copied placeholders, and
`AUTOTASK_PROVIDER=autotask`.

The application container should not run as root unless there is a specific,
documented reason.

Persistent PostgreSQL data must be stored in a Docker volume or another
documented persistent storage location.

Compose uses `COMPOSE_PROFILES=local-db,bundled-edge` by default.
`local-db` decides whether the bundled PostgreSQL service is deployed.
`bundled-edge` decides whether the bundled nginx and `cloudflared` services are
deployed together. Local single-host installs should enable both profiles
unless they intentionally use remote PostgreSQL, an external edge, or both.
Remote PostgreSQL installs should disable `local-db` and set `DATABASE_URL` to
the remote `postgresql+psycopg` connection URL. External nginx/cloudflared
installs should disable `bundled-edge` and route through an nginx service that
mirrors the bundled proxy's blocked paths, sanitized forwarded headers,
WebSocket handling, scoped restore upload limit, and app-styled error pages.
Provider-style `postgresql://` and `postgres://` URLs must be normalized to the
installed psycopg 3 driver before app startup or Alembic migrations create a
database engine. Keep app-side database connections bounded with the documented
pool and timeout settings.
Pushover health notifications are optional and best-effort. Compose, Swarm,
`.env.example`, and README docs must stay aligned when adding or changing
`PUSHOVER_*` or `APP_HEALTH_*` variables. Pushover user and app keys are
secrets and must stay in environment variables, Docker secrets, or another
approved secret store. The in-app monitor reports degraded, changed, hourly
still-degraded, and restored app health only while the app process is running; full
host/container/process-down alerts require an external monitor against
`/health/live`. `DEV_BUILD=true` must suppress Pushover health notifications
regardless of `PUSHOVER_ENABLED`.
Diagnostics-authorized administrators may acknowledge the exact current issue
fingerprint globally for the running app process. Acknowledgement suppresses
unchanged reminder messages until the issue set changes or recovers and does
not need to survive an app restart.

Production Swarm deployment uses `docker-stack.yml`, the `tpapp` and `tpnginx`
service names, private GHCR images selected by `TICKET_PILOT_APP_IMAGE` and
`TICKET_PILOT_NGINX_IMAGE`, and the `http://tpnginx:<HTTP_PORT>` Cloudflare Tunnel
origin. Dev Swarm deployment uses `docker-stack.dev.yml`, the `tpdapp` and
`tpdnginx` service names, dev-tag values in the same per-stack image variables,
and `http://tpdnginx:<HTTP_PORT>`. `HTTP_PORT` defaults to the private overlay
port `80`; do not publish it through the Swarm routing mesh because Swarm cannot
restrict a published port to loopback.
Run two `cloudflared` replicas with at most one replica per node in production.
The dev stack uses one `cloudflared` replica for the smaller test deployment.
The per-stack `TICKET_PILOT_SWARM_STORAGE_PATH` defaults to
`/mnt/swarm-storage/ticket-pilot` in production and
`/mnt/swarm-storage/ticket-pilot-dev` in dev. Both NFS roots are mounted on every
eligible node without deployment-time ownership or mode changes. Bind only
automatic backups and the faster-whisper model cache under those paths.
App, Nginx, and `cloudflared` operational logs must go only to stdout/stderr.
Each stack must use its own remote PostgreSQL database and deployment secrets;
do not add a file-backed database service unless explicitly requested.

Health checks should be added for services where practical.
PostgreSQL health checks must allow enough startup grace for first-time volume
initialization so Docker Compose or Portainer does not abort the app stack while
the database is still bootstrapping.
Compose dependencies must not require the local PostgreSQL service when the app
is configured for a remote database. The app entrypoint should wait briefly for
database connectivity, run migrations when possible, and then start the web
process in temporary-service mode if PostgreSQL remains unavailable. While the
database is unavailable, DB-backed routes must render an app-styled **Service
Temporarily Unavailable** page that auto-refreshes `/login` and does not expose
database, network, code, or stack details.

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
Use changelog headings in the form
`## 1.2.0 - 07.02.2026 - Release title`: write the version number without a
leading `v` and without brackets, use `MM.DD.YYYY` release dates, then place
the version title after the date. Detailed `CHANGELOG.md` and concise
`WEB_CHANGELOG.md` version entries should use the applicable non-empty
`Added`, `Changed`, and `Fixed` subsections; omit a subsection from that
version when it has no bullets.

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
own checkout or worktree, Docker Compose project or Swarm stack name, `.env`,
database volume or remote database, backup path, Cloudflare Tunnel token,
public hostname, WebAuthn origin, and environment-specific `HTTP_PORT`. This
keeps dev testing from sharing production sessions, backups, database state, or
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

The application is a FastAPI project under `ticket_pilot/`.

- `ticket_pilot/main.py` creates the FastAPI app, registers routers, applies
  session, Cloudflare Access, CSP, and security-header middleware.
- `ticket_pilot/version.py` owns the source-controlled application version shown
  on `/help`, `/changelog`, and diagnostics. Advance it only when requested and
  keep it aligned with `pyproject.toml`.
- `ticket_pilot/session_timeout.py` clears expired local authenticated sessions
  according to the configured `APP_SESSION_TIMEOUT_HOURS` value and rejects
  managed web-user sessions that were disabled or administratively invalidated.
- `ticket_pilot/config.py` loads every runtime setting from environment variables.
  Production must use `AUTOTASK_PROVIDER=autotask`; Autotask resource IDs are
  stored on managed web users, not in config. Remote faster-whisper, AI
  cleanup, help assistant, password reset, SMTP, and Turnstile settings live
  here as environment-backed values. `DEV_BUILD=true` marks a dev runtime by
  turning the authenticated Help button yellow, adding `-DEV` to the
  full-browser header version label, showing `DEV` on `/help`, suppressing
  Pushover health notifications, and keeping development/test deployments
  visually distinct from production. `ADMIN_CONTACT_EMAIL` configures the
  end-user support contact shown in disabled-account messages, AI Help answer
  footers, and managed-user welcome emails.
- `ticket_pilot/database.py` owns SQLAlchemy engine/session setup.
- `ticket_pilot/models.py` defines persistent tables for managed web users,
  managed-user session invalidation cutoffs, per-user preferences, password
  reset token hashes and throttles, jobs, audit events, sanitized login
  attempts, and Autotask submission attempts.
- `ticket_pilot/enums.py` defines workflow, transcription, and ticket-status
  enums used by routes, services, templates, and migrations.
- `ticket_pilot/time_utils.py` centralizes UTC/local conversion and 15-minute
  rounding. Do not duplicate rounding logic elsewhere.
- `ticket_pilot/ui.py` owns shared template context, including the content-derived
  static asset version used to bust browser/PWA caches after CSS or JavaScript
  changes without changing the source-controlled app version.
- `ticket_pilot/services/changelog.py` parses the source-controlled
  `WEB_CHANGELOG.md` into concise plain-text release entries for authenticated
  display.
- `ticket_pilot/services/help_assistant.py` builds bounded end-user help context
  from the primary `AI_HELPER.md` knowledge base plus matching snippets from
  `USER_MANUAL.md`, `WEB_CHANGELOG.md`, agent guidance, and selected app source,
  then calls Gemini's OpenAI-compatible chat-completions API only when
  server-side AI Help is configured.
- `AI_HELPER.md` is the comprehensive, non-technical end-user support knowledge
  base sent to the Help LLM. Keep it synchronized with user-visible workflows,
  settings, field rules, common messages, frequently asked questions, and safe
  high-level behavior. It must not contain secrets, private deployment values,
  source instructions, or administrator-only diagnostic procedures.
- `USER_MANUAL.md` is the full end-user manual. It must describe only surfaces
  normal managed web users can access and must not document Diagnostics or
  other admin-only pages.
- `ticket_pilot/services/transcription.py` owns local and remote speech-to-text
  providers, including remote faster-whisper URL safety checks and bearer-token
  handling.
- `CHANGELOG.md` contains detailed release notes for operators and agents.
  `WEB_CHANGELOG.md` contains short user-facing release notes for `/changelog`.
- `ticket_pilot/routes/auth.py` handles config super-admin login, managed web-user
  login, logout, and local authenticated sessions, including sanitized
  database-backed login-attempt records.
- `ticket_pilot/routes/password_reset.py` handles self-service managed-user
  password reset requests, sanitized Turnstile browser diagnostics, and token
  completion without account enumeration.
- `ticket_pilot/routes/passkeys.py` handles managed-user passkey registration,
  deletion, and passkey login challenge/verification routes.
- `ticket_pilot/routes/mobile.py` handles `/work`, active job start/end/save,
  active rounded-start adjustment, WebSocket recording streams for active and
  unsubmitted review jobs, compatibility recording uploads, description text
  saves, and Autotask company autocomplete.
- `ticket_pilot/routes/review.py` handles review listing, edit/save/accept/retry,
  saving the first client selection for an empty active review job, updating or
  deleting existing submitted Autotask records, ticket lookup for a selected
  job, and explicit local **Delete time entry** / **Delete note** cleanup.
- `ticket_pilot/routes/users.py` handles the super-admin managed web-user page,
  including add/edit/enable/disable/delete/archive/restore behavior, Autotask
  Resource lookup, active service-desk role lookup, and session invalidation
  when accounts are disabled or archived.
- `ticket_pilot/routes/configuration.py` handles authenticated managed-web-user
  configuration such as immediate independent background/highlight selection
  and explicit managed-user password changes.
- `ticket_pilot/routes/changelog.py` handles authenticated `/changelog` release
  history used by the Help page's **version changelog** overlay and by direct
  authenticated fallback navigation.
- `ticket_pilot/routes/help.py` handles authenticated `/help` and `/help/ask`
  for the Help page and stateless, single-question help assistant answers.
- `ticket_pilot/routes/debug.py` handles the canonical `/diagnostics` page,
  backward-compatible `/debug` aliases, the
  sanitized successful/failed login windows, disk-space monitor, database
  diagnostics, full backup/restore actions, managed web-user session
  invalidation, and the Autotask API connectivity test.
- `ticket_pilot/routes/health.py` exposes private container health endpoints.
- `ticket_pilot/routes/pwa.py` serves the web app manifest and root-scoped
  service worker for installed mobile app behavior. The service worker must not
  cache authenticated job, session, Autotask, or transcription data.
- `ticket_pilot/services/system_health.py` owns shared app-health snapshots,
  including disk usage, cached Autotask API health, database status, database
  latency, database connection-pool pressure, and active login-protection
  state used by Diagnostics, the authenticated top-bar degraded-health Help link,
  and best-effort admin notifications. Storage-probe operating-system errors,
  including stale network-filesystem handles, must become a critical health
  issue without preventing ordinary authenticated pages from rendering.
- `ticket_pilot/services/app_health_monitor.py` runs the optional in-process
  app-health notification loop, sends immediate changed/restored notices, and
  repeats an unchanged degraded state at the configured hourly interval.
- `ticket_pilot/services/pushover.py` owns best-effort Pushover message delivery
  and must never log configured user or app keys.
- `ticket_pilot/services/database_diagnostics.py` collects display-safe database
  connectivity, latency, migration, and connection-pool stats for Diagnostics.
- `ticket_pilot/services/jobs.py` owns core job state transitions and must remain
  the primary place for workflow and job-ownership validation.
- `ticket_pilot/services/autotask.py` owns Autotask providers, connectivity tests,
  company/ticket lookup, per-user resource service-call lookup, cache behavior,
  pagination, active service-desk role lookup, submission-time status mapping,
  time entry submission, existing-entry updates, and existing-entry deletes.
- `ticket_pilot/services/users.py` owns managed web-user validation, optional
  Autotask Resource email and default-role storage, password hashing and
  changes, first-user legacy job claiming, and delete/archive/restore rules.
- `ticket_pilot/services/session_control.py` owns server-side managed web-user
  session invalidation cutoffs used by diagnostics, user disable, and user
  archive actions.
- `ticket_pilot/services/preferences.py` owns per-authenticated-user
  configuration validation and persistence.
- `ticket_pilot/services/passkeys.py` owns WebAuthn relying-party/origin
  resolution, challenge generation, passkey verification, public credential
  storage, credential counters, and safe passkey deletion.
- `ticket_pilot/services/ai_cleanup.py` owns server-side Gemini, Groq, Ollama,
  and LM Studio summary cleanup, including request construction,
  provider-specific instruction placement, private-network provider URL
  validation, safe response parsing, and provider error normalization.
- `ticket_pilot/services/transcription.py` owns speech-to-text provider behavior.
- `ticket_pilot/services/audit.py` records immutable audit events.
- `ticket_pilot/services/backups.py` creates and restores portable gzip JSON full
  database backups, writes startup and hourly automatic backup files, and
  enforces automatic backup retention. `/diagnostics` may download retained automatic
  backups only after strict filename validation, and labels retained automatic
  backups as startup or hourly when creation audit metadata is available.
- `ticket_pilot/services/login_failures.py` writes and reads sanitized
  successful/failed login attempts from the database and generates sanitized
  JSONL downloads for Diagnostics. `LOG_LEVEL` controls stdout/stderr verbosity
  and must be one of `DEBUG`, `INFO`, `WARNING`, or `ERROR`.
- `ticket_pilot/services/login_protection.py` enforces local pre-authentication
  lockout, increments persistent consecutive failed-login counters by trusted
  enforcement IP and username, stores sanitized failed-login database records,
  and triggers Cloudflare auto-blocking at the configured threshold.
- `ticket_pilot/services/cloudflare_blocks.py` owns app-managed Cloudflare zone
  IP Access Rule create/delete calls and allowlist checks. It must never list,
  edit, or delete Cloudflare rules that are not tracked in TicketPilot's
  `cloudflare_ip_blocks` table.
- `ticket_pilot/templates/` contains Jinja pages for mobile, review, users,
  config, changelog, debug, and authentication views.
- `ticket_pilot/static/` contains browser-side JavaScript, CSS, PWA metadata,
  and the canonical source-controlled TicketPilot logo and app-icon files under
  `static/icons/`. Keep supplied branding sources unchanged and remove
  superseded logo/icon files when artwork is replaced.
- `docs/design/` contains `theme_palettes.svg`, the only maintained reference
  defining all eight selectable background profiles and ten automatic
  highlight/counterpart pairs.
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
   row actions for edit, delete, password reset email, and welcome email. The
   user status pill toggles that managed user between Enabled and Disabled.
   The add form suggests a username from the full name, and add/edit forms can
   query Autotask Resources to select the matching resource ID and capture the
   returned email address.
   The add form sends a welcome email by default when the stored email address,
   `APP_PUBLIC_BASE_URL`, and mail delivery settings are configured, unless the
   super admin unchecks that option. Account emails refer to the app as
   **TicketPilot**.
   Delete actions fully remove users that have no jobs. Users with linked jobs
   are hidden and signed out, their passkeys, reset tokens, and preferences are
   removed, and their jobs remain attached to the hidden row so adding another
   user with the same Autotask resource ID restores that history. The Users list
   also shows the last successful managed-user login time, stamped after
   password or passkey login, or `Never`, plus a green/red key icon for whether
   Device sign-in passkeys are registered. The first visible managed web user
   claims any existing unowned jobs from earlier single-user installs.
3. A managed web user may open `/config` to choose among three light and five
   dark background profiles and independently choose one of ten highlight
   colors for their own login, enable the default-off **Submit from Work in Progress**
   option, change their password, and add or delete passkeys. If the account is
   using a temporary super-admin-created or reset password, `/config` shows only
   the required password-change flow until the user chooses a new password.
   Config changes save and apply immediately without a visible save action,
   except password and passkey actions which are explicit. The password card
   shows password requirements. The config super admin has no `/config` access
   and always uses Default Dark with Teal.
4. A managed web user opens `/work`.
5. The `/work` page renders from local application state without running an
   Autotask API contactability check. After the page has loaded, browser
   JavaScript queries `/work/service-calls` to populate service-call start
   cards for the selected local date and that user's Autotask resource,
   including each call's scheduled local date and start/end time range. The
   mobile date navigator
   can move backward/forward by day or open a calendar picker, and its visible
   label shows `Today`, `Yesterday`, or `Tomorrow` with the weekday when
   applicable; other dates show the month, ordinal day, and weekday without
   the year.
   Service-call starts are still verified server-side for the submitted date
   and resource.
   The browser list and start route both filter out service calls for tickets
   that already have a local TicketPilot time entry with ticket status Complete
   or Follow up for the current managed user.
6. User starts Job 1 or Job 2. Blank Start Work creates a local active job
   owned by that web user without first probing Autotask. At most two active
   jobs may exist at once per web user.
7. After the job starts, the user may adjust the editable local **Job date** and
   search Autotask companies by client name. The saved client must be selected
   from a server-returned Autotask company option so the client display name and
   company ID verify together; typed-only names must not be saved. The selected
   client may still be changed until an open ticket is selected for the job.
8. User chooses an open Autotask ticket from the active-job ticket panel. If no
   tickets are loaded yet, the whole panel is the load control and shows a
   spinner while Autotask data is being queried. Ticket options show detected
   Remote/On-Site/Not specified labels from ticket title and description text,
   falling back to remote-only Autotask ticket sources such as `RMM Alert`,
   `Datto Alert`, `BCDR Alert`, and `Email Alert` when text detection has no
   result. Remote and On-Site color treatment matches service-call cards.
   Ticket choices also show **Start** from Autotask `Tickets.createDate` and
   **Due by** from `Tickets.dueDateTime`. Mobile ticket numbers are populated
   from that selection instead of manual
   entry. Selection never patches Autotask ticket status; it stores verified
   local ticket metadata and defaults the editable local ticket status to
   In progress until the job's time entry is submitted. The selected ticket
   status is shown and editable on Work in Progress. Read-only ticket
   descriptions stay in short scrollable boxes on Work in Progress and review
   detail; if Autotask returns no description, keep the card visible with a
   clear no-description message. After ticket selection, the client name is
   locked for that job in Work in Progress, Review, and server-side save/end
   handlers.
9. User chooses whether the work is Remote or On-Site. On active Work, changing
   this mode keeps the start time unchanged and recalculates the stop to the
   later of the location minimum or the current rounded block. The mode is
   stored on the job and appears as the leading `Remote. ` or `On-Site. ` prefix
   in the review summary textarea so it can be corrected before Autotask submission.
10. User records notes during an active job from the Summary notes action row,
   where **Record** sits beside the optional **AI Cleanup** action. Review
   detail uses the same paired summary action row for unsubmitted jobs. On
   full-browser Work in Progress cards, the End Work/Delete row sits directly
   below Record/AI Cleanup, and one shared save/recording/AI Cleanup status
   line sits below all action buttons. Review detail uses the same single-line
   status treatment below the review workflow actions. The record button becomes
   a stop button while audio chunks stream to
   the server over WebSocket. Recording, sending, and converting progress use
   plain status text, and stopping capture keeps the disabled record button in a
   loading state until the final transcript returns.
11. When enabled, user can click **AI Cleanup** to send the current summary text
   through the configured server-side cleanup provider. On
   mobile, progress and failure details use the same plain-text status line as
   save and audio recording messages, while the **AI Cleanup** button itself
   shows the spinner during cleanup. The returned text replaces the summary
   textarea and remains subject to normal save/review behavior.
12. User can save active job edits before ending work.
13. User ends work with a mandatory verified Autotask client. With the default
    workflow, the active-card **End Work** action shares a row with the
    destructive **Delete** action, and the job moves to review. If **Submit from
    Work in Progress** is enabled, the end-work action submits to Autotask
    immediately after validating ticket number, ticket status, rounded end
    time, verified client, and summary notes. Missing local submission fields
    leave the job active so the user can fix them; Autotask provider failures
    move the job to the failed-submission review state with the safe error
    message. The option is not a workflow availability toggle; it only selects
    direct Autotask submission versus review-first submission.
14. User reviews the job from `/review`, edits time/status/notes if needed,
    optionally records more audio notes before Autotask submission, and keeps
    the selected client/ticket identity read-only once selected. If the job is
    still active and has no selected client, Review
    detail can save the first client/company from the same server-backed
    Autotask company search before ticket lookup. Review detail groups action
    controls into compact rows with at most two buttons per row; submitted time
    entries pair **Submit changes** with **Delete From Autotask**. Submitted
    ticket notes show **Submit changes** without an Autotask delete action
    because that API does not document TicketNotes deletion. Local unsubmitted
    entries pair the submit action with **Delete time entry** or **Delete note**
    when possible. Active jobs selected in Review show **End
    Work** or **End Note** paired with the matching delete action and post to
    the normal end-work route. Directly
    submitted jobs still appear in Review for submitted-entry **Submit
    changes** actions; only submitted time entries also expose **Delete From
    Autotask**. Active jobs opened in Review show the same rounded stop preview
    as Work in Progress, but review
    saves must not apply that displayed end time until the job is actually ended.
15. Accept/retry submits a reviewed job to Autotask idempotently with the
    owning managed web user's resource ID.
16. Successfully submitted jobs can use **Submit changes** for
    supported field updates against the existing Autotask `TimeEntries` or
    `TicketNotes` row. Submitted time entries may also use **Delete From
    Autotask** to remove the external record and return the local job to review;
    submitted ticket notes must not expose this unsupported action. The
    selected Review detail must
    not display the stored Autotask external ID. **Submit changes** reasserts
    the selected local ticket status in Autotask every time it patches the
    existing external row. It may reopen previously Complete tickets to In
    progress before patching the external record, then apply the selected final
    status after the patch when needed.
    If time-entry **Delete From Autotask** fails, a session-scoped dialog can
    offer a local-only purge from TicketPilot review while warning that the
    Autotask record may still exist.
    Ticket/client identity, local delete, accept/resend, and retry stay blocked
    while the job remains submitted.
17. Submission attempts and important state changes are recorded for audit and
    diagnostics.
18. Managed users without a passkey see a phone-sized Home prompt to set up
    device sign-in once after a successful login. `/config` always shows device sign-in
    management backed by passkeys. The login page places Device sign-in under
    the password sign-in button. Later device sign-in uses
    `/login/passkey/options` and `/login/passkey/verify`; failed or canceled
    passkey login must leave the normal password form available.
19. Authenticated users may open `/help` from the shared header Help button.
    `/help` starts with the **Ask AI for help** card, then shows
    **Operational Status**, then shows the current source-controlled version,
    `DEV` when `DEV_BUILD=true`, `Released: MM.DD.YYYY` when the current
    changelog entry has a release date, and a **version changelog** button that
    opens release notes in an overlay. The shared degraded-health top-bar
    button opens this **Operational Status** card directly. The overlay shows
    previous versions as full-width cards without timeline marker dots and only
    labels dates for released versions. `/changelog` remains authenticated as a
    fallback route and shows prior concise release notes parsed from
    `WEB_CHANGELOG.md`. The current-version panel must show that version's
    simple change list, not only the release title.

## Current Autotask Dependency

Autotask is not an optional production dependency anymore. The app depends on
Autotask Companies and Tickets to help select the correct ticket before work is
submitted.

In production:

- `APP_ENV=production` requires `AUTOTASK_PROVIDER=autotask`.
- `APP_USERNAME`/`APP_PASSWORD` authenticate the config super admin only.
- Each managed web user must be created on `/users` with an Autotask resource
  ID before that person can start work.
- `/work` and blank Start Work do not run Autotask contactability probes.
- Service-call loading, company lookup, ticket lookup, and Autotask submission
  still call Autotask only when those specific workflows need provider data.
  Service-call and open-ticket selection are read/query-only against Autotask
  and must not patch remote ticket status before TimeEntries or TicketNotes
  submission.
- Time-entry and ticket-note submission patch `Tickets.status` to match the
  selected TicketPilot ticket status. Configure all `AUTOTASK_STATUS_*_ID`
  values and ensure the Autotask API user can patch `Tickets.status`; otherwise
  submission fails without marking the local job submitted.
- Submitted **Submit changes** actions also patch `Tickets.status` to match the
  selected TicketPilot ticket status. The removed
  `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED` setting must not be reintroduced.
- Super-admin resource lookup on `/users` calls Autotask Resources only through
  the server-side provider; browser code never contacts Autotask directly.
  Returned resource email metadata is optional and is stored only when a user
  selects a resource that includes one.
- The `/diagnostics` page provides the supported manual **Test Autotask API** action.
  The authenticated desktop navigation labels this route as **Diag**, while the
  page itself is titled **Diagnostics**.
- Autotask provider HTTP/status failures, failed time-entry create/update/delete
  results, and failed Diagnostics connectivity tests must mark the cached
  Autotask health state as degraded until a later Autotask API request or
  connectivity test succeeds. This cached state powers the authenticated
  top-bar degraded-health Help link, Diagnostics health banner, and optional
  best-effort Pushover notification loop; page rendering must not run a fresh
  Autotask contactability probe.
- Live Autotask HTTP calls are capped by `AUTOTASK_MAX_CONCURRENT_REQUESTS`,
  defaulting to 2. Keep all direct REST traffic inside
  `ticket_pilot/services/autotask.py` so this process-local and PostgreSQL
  advisory-lock limiter is always applied.
- The `/diagnostics` page provides a Diagnostics-admin **Log out web users** action
  that invalidates all managed web-user sessions without ending the config
  super-admin session. Managed Admin users are included in that invalidation
  because they are managed web users. The button should sit centered below the
  explanatory text, using a wider-than-tall destructive button shape inside the
  session-controls card.
- The `/diagnostics` page provides per-row failed-login hide controls, per-row
  Cloudflare block/unblock controls, and an app-managed Cloudflare blocked IP
  card. Automatic Cloudflare blocking happens after
  `CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS` consecutive failed local logins
  from the same trusted enforcement IP and submitted username unless that IP
  matches `CLOUDFLARE_IP_BLOCK_ALLOWLIST`; successful local password or Device
  sign-in login resets that enforcement IP and username failure counter to
  zero. The same threshold also starts the local
  `LOGIN_LOCAL_LOCKOUT_MINUTES` pre-authentication lockout.
- The shared app-health snapshot must monitor disk space, cached Autotask
  operation failures, database availability, database query latency, database
  connection-pool pressure, active local login lockouts, and app-managed
  Cloudflare IP blocks. The `/diagnostics` page should show a yellow or red
  app-health banner at the top when any monitored issue is active.
  A temporarily unreadable monitored storage path must report a critical
  **Storage unavailable** condition while normal app workflows remain usable;
  health collection must not turn a stale backup mount into a page-level 500.
  Disk alerts must use free space only: warning below
  `APP_HEALTH_DISK_WARNING_FREE_MB`, defaulting to 1000, and critical below
  `APP_HEALTH_DISK_CRITICAL_FREE_MB`, defaulting to 250. Used percentage is
  display-only and must not trigger an alert.
- The optional Pushover health monitor is best-effort and in-process. It can
  notify on degraded, changed, hourly still-degraded, and restored monitored
  health only while the app process is running. Keep `PUSHOVER_USER_KEY` and `PUSHOVER_APP_KEY` in
  environment or Docker secrets, never source control or logs. Full
  host/container/process-down detection still requires an external monitor
  against `/health/live`. `DEV_BUILD=true` must disable Pushover notifications
  even when `PUSHOVER_ENABLED=true`.
- The `/diagnostics` disk-space card combines monitored paths when used bytes and
  total bytes match exactly. The `/diagnostics` database card may show safe
  connectivity, latency, backend/driver, migration revision, and pool counters,
  but must not show connection strings, hosts, database names, usernames, or
  passwords. On full-browser Diagnostics, the disk-space and session-control
  cards should share one same-height row above the database card while phone
  layouts keep stacked cards.
  Wide Diagnostics tables, including Autotask submission attempts and retained
  automatic backups, should remain horizontally scrollable on phone layouts so
  row actions stay reachable.
- Mock Autotask mode is only for tests and isolated development.

## Documentation Maintenance Rules For Agents

When changing workflow, Autotask behavior, security behavior, Docker/runtime
configuration, database schema, or diagnostics:

- Update this file if the top-level structure or required reading changes.
- Update the relevant file in `docs/agent-skills/`.
- Update `README.md` when operators need to know about behavior or deployment
  changes.
- Update `USER_MANUAL.md` when managed-user visible behavior, labels,
  workflows, settings, or troubleshooting messages change.
- Update `AI_HELPER.md` for every managed-user-visible feature, behavior,
  setting, field rule, troubleshooting message, or support answer change so
  AI Help remains aligned with the running application.
- Update `CHANGELOG.md` for every user-visible, security, workflow, database,
  Docker, Autotask, transcription, or diagnostic change.
- Update `WEB_CHANGELOG.md` for every released version with short web-facing
  bullets that are simpler than the detailed `CHANGELOG.md` entry. Exclude
  diagnostics, debug-page, super-admin-only, operator-only, and agent-facing
  changes from `WEB_CHANGELOG.md`.
