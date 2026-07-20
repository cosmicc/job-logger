# Job Logger Agent Skill: Security

Read this file before changing authentication, sessions, Cloudflare Access,
CSRF, audit logging, diagnostics, file uploads, transcription, Docker runtime
settings, or anything that handles secrets.

## Security Model

The app uses defense in depth:

- Cloudflare Access can protect the public hostname before the request reaches
  the app.
- The app still enforces its own authenticated server-side session.
- State-changing actions require CSRF protection.
- Server-side services validate workflow state and user-submitted fields.
- Important actions create immutable audit events.

Never rely on hidden fields, browser state, disabled buttons, or mobile UI
choices for security decisions. The server remains authoritative.

## Authentication And Sessions

Authentication routes live in `job_logger/routes/auth.py`. Managed-user
password reset routes live in `job_logger/routes/password_reset.py`.
Managed-user passkey routes live in `job_logger/routes/passkeys.py`.

`APP_USERNAME` and `APP_PASSWORD` authenticate only the config super admin. That
account can manage `/users`, view all review jobs, use diagnostics, and run
backup/restore, but it must not start, edit, submit, delete, record, or
AI-cleanup jobs because it has no Autotask resource ID. Work-entry users are
database-managed `WebUser` rows created on `/users`; they store full name,
username, salted password hash, required Autotask resource ID, optional email
captured from Autotask Resource lookup, optional default service-desk role ID
selected from that resource's active Autotask roles, last successful login time,
Admin Diagnostics access, and disabled state.
Disabled web users must be blocked from new logins and from old signed sessions.
Deleted web users with no jobs are fully removed. Deleted web users with linked
jobs are archived, hidden from `/users`, blocked from every login path, signed
out through the session invalidation cutoff, stripped of passkeys, reset tokens,
account reset throttles, and preferences, and restored automatically when a new
managed user is added with the same Autotask resource ID.
The `/users` add form has a default-on **Send welcome email** option for new
managed users. Send it only to the stored managed-user email address, use
`APP_PUBLIC_BASE_URL` for the app link, include the username, temporary-password
change instruction, mobile install steps, Device sign-in guidance, and
`ADMIN_CONTACT_EMAIL` when configured, call the app **Autotask Job Logger**, and
never include the temporary password.
Welcome email delivery must be non-blocking for user creation. Audit only safe
metadata such as user ID, username, provider, whether an email was saved, and
bounded delivery errors.
The `/users` list must not expose internal Autotask resource ID or role ID
values, but add/edit forms may still save them for server-side Autotask use.
Row actions may send a password reset email or resend the welcome email for an
enabled managed user only. Disabled users must be blocked from those email
actions. The user-list Enabled/Disabled status pill is a CSRF-protected state
toggle. Disabling through that pill must invalidate that user's existing signed
sessions, and enabling through the pill must preserve the account row without
resetting passwords, passkeys, roles, email, or job history. Admin-sent reset
links may be created even when public self-service password reset is disabled.
Managed-user passwords must be at least 8 characters and include lowercase,
uppercase, number, and symbol characters. Enforce that rule server-side before
hashing; browser validation is only a usability aid. Passwords created or reset
by the config super admin are temporary. On the next managed-user sign-in,
`job_logger/session_timeout.py` and
`job_logger/services/session_control.py` must allow only `GET /config`,
`POST /config/password`, and logout until `/config/password` successfully
changes the password and clears `web_users.password_must_change`.
`ADMIN_CONTACT_EMAIL` is an optional Docker/env support contact. Show it only
after the app has verified a disabled account through the correct password,
passkey assertion, or existing signed session state. Invalid usernames and
wrong passwords must keep the generic invalid-credentials message so login does
not reveal account existence.

Self-service password reset is optional and hidden unless
`PASSWORD_RESET_ENABLED=true`. `/forgot-password` and `/reset-password/{token}`
must stay behind Cloudflare Access when Access is configured, and every form
must validate CSRF. Reset requests must never reveal account existence. For a
valid submitted email and, when enabled, Turnstile result, show the same
generic browser message whether zero, one, duplicate, or disabled accounts
exist. Send email and create a token only when exactly one enabled `WebUser`
row matches the submitted email address. Store only an HMAC-SHA256 token hash
keyed by `APP_SECRET_KEY`; never store, log, audit, or display the raw token or
full reset URL. Reset links must be unique per request, expire after
`PASSWORD_RESET_TOKEN_TTL_HOURS` defaulting to 24, work once, clear
`web_users.password_must_change` through the normal password helper, and
invalidate existing managed-user sessions on success. Reset throttles are
independent of Turnstile: per IP 5 requests per 15 minutes, per submitted email
3 per hour, and per matched account 1 email per 15 minutes. Store email
throttle keys and audit email identifiers as HMAC hashes, not raw submitted
addresses. Also count consecutive syntactically valid emails that do not match
exactly one enabled account by trusted enforcement IP. Missing, disabled, and
duplicate matches count toward
`PASSWORD_RESET_FAILED_ATTEMPTS_BLOCK_THRESHOLD`, defaulting to 3. At the
threshold, apply `LOGIN_LOCAL_LOCKOUT_MINUTES` and optional app-managed
Cloudflare blocking; reset the counter after one unique enabled match. Keep the
browser response non-enumerating, store no raw email in that IP counter, and
honor `CLOUDFLARE_IP_BLOCK_ALLOWLIST`. `TURNSTILE_ENABLED=false` is allowed in
development and production,
but the flow must still use CSRF, Cloudflare Access when configured, rate
limits, generic non-enumerating responses, and HMAC-stored token hashes.
Reset-token pages and completion must keep accepting valid admin-sent reset
tokens even when `PASSWORD_RESET_ENABLED=false` hides `/forgot-password`.
Do not bypass HMAC lookup, expiry, single-use, CSRF, password rules, or session
invalidation for those admin-created links.
Password reset mail delivery is selected by `MAIL_MODE`. `smtp` uses the
existing SMTP transport and `smtp2go` uses SMTP2GO's HTTPS API with
`MAIL_SMTP2GO_API_KEY`. Never log or persist SMTP passwords, SMTP2GO API keys,
full reset URLs, or welcome-email provider secrets.
When Turnstile is enabled, the static forgot-password browser page must load
Cloudflare's standard `api.js` script, avoid the implicit `cf-turnstile`
auto-render class, and render the widget through the local password reset
script after the Cloudflare API is available. The local script may retry the
explicit `api.js?render=explicit` URL if the standard API script fails before
rendering. Do not call `turnstile.ready()` from a deferred script. Keep the
submit button disabled until a non-empty Turnstile token is returned, and show
a visible verification status. That browser guard is usability only;
server-side Turnstile verification remains mandatory. Server-side Siteverify
handling must also reject responses whose returned `action` is not
`password_reset` or whose returned hostname does not match
`APP_PUBLIC_BASE_URL`. The forgot-password page may post CSRF-protected
same-origin Turnstile browser lifecycle diagnostics for app logging. Keep those
events strictly sanitized: event names, script host/path metadata, callback
state, render state, token length, request IP, and user agent are acceptable;
raw tokens, emails, reset URLs, cookies, secrets, site keys, and API keys are
not.

Local authenticated sessions must expire after `APP_SESSION_TIMEOUT_HOURS`.
`job_logger/session_timeout.py` enforces the server-side timestamp check, and
Starlette session cookies use the same configured lifetime. Every successful
password or passkey login must stamp the session with the authentication time
and method so stale signed cookies cannot remain valid past the configured
timeout. Successful managed-user password and passkey login also stamp
`web_users.last_login_at_utc` for the super-admin user list; this metadata is
informational and must not replace session timeout or invalidation checks.
Managed web-user sessions can also be invalidated by a per-user UTC cutoff in
the `web_users` row. `job_logger/services/session_control.py` owns that cutoff
logic. Disabling one user or using the Diagnostics **Log out web users** action
must clear old managed-user cookies on the next request without signing out the
config super admin.
The login page's **This is a public device** checkbox is default-off, appears
below the forgot-password link, and keeps its explanatory copy in a hover/title
hint. While checked, the Device sign-in button must be visibly greyed out,
disabled, and unclickable; unchecking it must restore the normal Device sign-in
button state. When selected for password sign-in, the session gets a 15-minute
inactivity timeout, suppresses the Home Device sign-in setup prompt, and must
reject new passkey registration while keeping normal authentication, CSRF,
disabled-user, and configured session-timeout enforcement intact.

Managed web-user passkeys are optional login credentials. The config super
admin must not register or use passkeys. Passkey registration is available only
after a normal managed-user login from `/config`; login remains available from
the password page through a separate passkey button above the username/password
form. Failed, canceled, or unsupported passkey authentication must leave the
username/password form usable.
User-facing controls should call this feature **Device sign-in** even though the
technical implementation remains WebAuthn/passkeys. The `/home` device sign-in
setup card is only a one-time phone-sized post-login prompt for managed users
without a passkey; `/config` must keep device sign-in setup available except
while the current login session is marked as a public-device session.
The super-admin `/users` table may show only passkey setup status, such as a
green/red icon or safe count. It must not expose credential IDs, public keys,
transports, AAGUIDs, user agents, or other authenticator metadata.

The app stores only WebAuthn public credential material: credential ID, public
key, signature counter, safe device metadata, creation time, and last-used time.
The private key and local unlock method remain on the user's phone, browser, or
passkey provider and must never be requested, logged, backed up separately, or
shown in diagnostics. Registration and authentication must use one-time session
challenges, require CSRF on browser fetches, require user verification, verify
the expected relying-party ID and origin, update signature counters after
successful assertions, and block disabled managed users. Passkey audit events
must contain only safe metadata such as user ID, username, credential row ID,
credential ID prefix, and failure reason.

The `/debug` page and all `/debug/*` actions are available to the config super
admin and to managed web users whose `web_users.is_admin` flag is enabled.
That managed-user Admin flag grants full Diagnostics access only, including
backup/restore, session invalidation, Autotask tests, failed-login hiding, and
Cloudflare block controls. It must not grant `/users`, super-admin review
scope, or any additional job workflow permissions. Normal managed web users
must not see the Diag/Diagnostics navigation item, and direct requests from
those sessions must receive 403 instead of being treated as anonymous login
redirects.
The cached app-health top-bar indicator is visible to every authenticated user
when app health is degraded. It may link to `/help#operational-status`, but
keep `/debug` authorization as the server-side source of truth for Diagnostics
and do not expose secrets, raw provider details, or specific issue labels in
the header; detailed troubleshooting belongs on Diagnostics. The header button
uses yellow for warning and red for critical. Diagnostics may show a yellow or
red app-health banner for admins while ordinary authenticated users see only
the compact top-bar Help status link.
The Diagnostics **Log out web users** action is CSRF-protected, audited, and
must invalidate only managed web-user sessions. It must not clear the current
config super-admin session. If a managed Admin user triggers it, that user is
included in the invalidation because the account is a managed web user. Keep
the destructive action button centered under the explanatory text inside the
session-controls card so the action is visually separated from the copy while
remaining easy to find.

The `/users/autotask-resources` lookup endpoint is super-admin-only and must
return only safe Autotask Resource metadata. Browser code can use it from
add/edit user forms to fill the resource ID field, but the server must still
validate the submitted resource ID and must never expose Autotask credentials or
raw remote error details.
The `/users/autotask-resource-roles` lookup endpoint is also super-admin-only.
It may return active `ResourceServiceDeskRoles.roleID` values and safe display
labels from `Roles.name` for the selected resource, but saving a submitted
default role must still re-query the server-side provider and verify that role
is active for the submitted resource ID. The stored managed-user value remains
the numeric role ID, not the display name.

Per-user configuration lives behind authenticated managed-web-user-only
`/config` routes. The config super admin has no user settings, must not see the
Config menu item or phone-sized Config icon, must receive 403 on direct
`/config` access, and always renders in dark mode. Phone-sized super-admin
navigation may show Users and Review on the left, with Help, Diagnostics, and
logout on the right; those links do not grant any capability beyond the
server-side authorization checks on the target routes. Phone-sized managed-user
navigation may show Home and Review on the left, with Help, Config,
Diagnostics only when `web_users.is_admin` is enabled, and logout on the right.
Non-admin managed users must not show Diag or Diagnostics navigation.
Phone-sized logout controls must submit the normal CSRF-protected `/logout`
form rather than using browser-only close behavior.
Theme and workflow preferences are not secrets, but autosaving them is still a
state-changing action that must require
authentication and CSRF. The workflow preference **Submit from Work in
Progress** must default off and must never allow the browser to bypass
server-side job ownership, workflow status, ticket, time, summary, or Autotask
submission validation. Disabled managed web users must not use old signed
sessions to change preferences. The `/config/password` route is
managed-web-user-only, requires CSRF, requires two matching password entries,
uses the managed-user complexity policy before hashing, and must audit only
safe metadata such as user ID or username. The password card should show those
requirements so users can fix validation failures before submitting. It must
clear the temporary-password flag after a successful change. Never log, audit,
or flash the raw submitted password.
The `/config` page should keep its cards ordered as **Appearance**,
**Password**, **Navigation**, **Workflow**, then **Device sign-in** so passkey
setup remains the final card on the page.

Disabling a managed web user from `/users` must invalidate that user's existing
signed sessions and preserve the row. Keeping a disabled row lets the login
screen explain that the account is disabled after the correct password is
submitted instead of treating the username as unknown. Deleting a managed web
user is different: users with no jobs are fully removed, while users with linked
jobs are archived and hidden. Archived users must look unknown to password
login, forgot-password email lookup, and the `/users` list, and they must be
blocked if an old signed session or passkey credential appears. When
`ADMIN_CONTACT_EMAIL` is configured, disabled-account explanations should
include the configured email address.

Application setup in `job_logger/main.py` configures:

- Signed server-side session cookie behavior through Starlette sessions.
- Server-side session timeout checks through `SessionTimeoutMiddleware`.
- Trusted host filtering when configured.
- Optional Cloudflare Access header enforcement.
- Security headers and Content Security Policy.

Production must not use default secrets or missing passwords.
When password reset is enabled, production must also have an absolute HTTPS
`APP_PUBLIC_BASE_URL` and configured SMTP mail. Turnstile site/secret keys are
required only when `TURNSTILE_ENABLED=true`. The Content Security Policy may
add only `https://challenges.cloudflare.com` for Turnstile `script-src` and
`frame-src` while keeping `frame-ancestors 'none'`.

Successful and failed local app login attempts are recorded as sanitized
database rows in `login_attempts`. The `/debug` login windows and generated
JSONL downloads may show timestamp, client IP details, submitted username,
account kind, authentication method, username length/truncation for failures,
user agent, request path, host/proxy metadata, reason, and
password-present/length metadata for failures. They must never include the raw
submitted password, session tokens, authentication headers, or Cloudflare
Access JWTs. The visible `client_ip` is diagnostics-only. In the bundled Docker
path, nginx must overwrite forwarded client headers with a single sanitized
Cloudflare Tunnel client IP, preferring `CF-Connecting-IP` and falling back to
the direct nginx peer. Local login lockout and automatic Cloudflare block
decisions must use the trusted enforcement IP from nginx-sanitized
`X-Real-IP`/`X-Forwarded-For`, falling back to the direct app socket peer only
outside the bundled proxy path. Retain direct socket and proxy headers as
supporting metadata only. Failed-login rows may be hidden from the `/debug`
table by setting `login_attempts.hidden_at_utc`; JSONL downloads are generated
from database rows and must remain sanitized. `login_failure_counters` stores
consecutive failures by trusted enforcement IP and case-insensitive submitted
username, and must reset to zero after a successful password or Device sign-in
login for that same IP/username key. When the counter reaches
`CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS`, the app must locally block
additional password or Device sign-in verification for
`LOGIN_LOCAL_LOCKOUT_MINUTES`, defaulting to 15. When Cloudflare blocking is
enabled, the app may create/delete only zone IP Access Rules tracked in
`cloudflare_ip_blocks`, must honor `CLOUDFLARE_IP_BLOCK_ALLOWLIST`, and must
not mutate unrelated Cloudflare rules. Diagnostics may create blocks from a
failed-login row or from a manual IP entry, and every path must require CSRF,
normalize the IP, apply the allowlist, and store a bounded safe reason that is
also used in the Cloudflare rule note. The successful-login table may use a
yellow account-kind chip for config
super-admin rows so they are easy to distinguish from managed web users, and
may show `Password` or `Passkey` method pills for the already-sanitized
authentication method. Successful-login, login-failure, and Autotask
submission-attempt diagnostics must stay paginated at 7 rows per page without
vertical table scrollbars. Cloudflare blocked-IP diagnostics stay paginated at
10 rows per page. Wide Diagnostics tables should stay horizontally scrollable on
phone layouts instead of compressing columns, especially when they include
per-row backup or Cloudflare actions. `LOG_LEVEL` controls stdout/stderr
verbosity and must be limited to `DEBUG`, `INFO`, `WARNING`, or `ERROR`.
`/debug` may also show
disk usage for app-visible storage paths such as `/` and
`${AUTOMATIC_BACKUP_DIR}`. Combine monitored paths when used bytes and total
bytes match exactly, and keep disk diagnostics read-only and limited to path,
usage, and warning/critical metadata. Warning and critical health state must be
based only on free space through `APP_HEALTH_DISK_WARNING_FREE_MB`, defaulting
to 1000, and `APP_HEALTH_DISK_CRITICAL_FREE_MB`, defaulting to 250. Used
percentage remains display-only. If a monitored path raises an operating-system
error, including a stale network-filesystem handle, represent that path as a
critical **Storage unavailable** health issue and omit fabricated usage values.
Health observation must fail safely so ordinary authenticated workflows keep
rendering while the mount is repaired. On full-browser Diagnostics, keep the
disk-space card and managed-web-user session-controls card together on a
same-height row above the database card; phone layouts should continue stacking
those cards.
The `/debug` database card may run a cheap `SELECT 1` probe and show safe
connectivity status, latency, backend/driver, migration revision, pool class,
pool counters, and configured pool limits/timeouts. It must not display the
database URL, host, database name, username, password, or raw exception details.
The shared app-health service uses the same disk warning/critical thresholds
for the authenticated top-bar degraded-health Help link and also tracks database
availability, database query latency, database connection-pool pressure, active
local login lockouts, app-managed Cloudflare IP blocks, and cached Autotask
operation failures. Page rendering may read local app-health checks, but it
must not run fresh external Autotask probes while building ordinary
authenticated pages. Cached Autotask health is tracked by semantic operation
type, so any user's failed Autotask operation keeps the indicator active until
that same operation type succeeds again. Successful unrelated Autotask
operations must not clear another active failure.
The optional Pushover health monitor is best-effort and in-process. It may
send degraded, changed, and restored messages only while the app process is
running; full host/container/process-down detection still belongs to an
external monitor against `/health/live`. `DEV_BUILD=true` must suppress
Pushover notifications even when `PUSHOVER_ENABLED=true`.
`DEV_BUILD=true` is not an authorization, environment-isolation, or safety
boundary.

## CSRF Rules

Forms use rendered CSRF tokens.

JSON or upload requests use the CSRF header validation path.

Any new state-changing route must validate CSRF before changing database state,
calling external APIs, or accepting uploaded content.

## Secret Handling

Secrets must come from environment variables, Docker secrets, or another
approved secret store.

Never commit or print:

- `.env` values.
- Autotask API username/key, secret, or integration code.
- Gemini or Groq API keys, private-network provider API keys, model server URLs,
  and private cleanup instructions.
- Session secrets.
- Database passwords.
- Cloudflare tunnel tokens.
- Cloudflare Access JWTs.
- SMTP passwords.
- Turnstile secrets.
- Pushover user keys or app tokens.
- Raw authentication headers.
- Raw audio.

Diagnostic pages and audit details must use safe summaries only.
Authenticated pages may show the source-controlled application version because
it is non-secret build metadata; do not source that value from environment
variables that could drift between containers. The shared header links to
`/help`, where authenticated users can see the current version and open the
version changelog overlay. Keep both the Help overlay and authenticated
`/changelog` fallback inside the app shell even though the version and release
notes are source-controlled metadata. The web changelog must come from concise
`WEB_CHANGELOG.md` entries, while
`CHANGELOG.md` remains the detailed operator/agent release record.

AI Help is an external AI integration for authenticated end-user support. Keep
`GEMINI_API_KEY` in runtime environment or secrets, never in source control.
Use `AI_HELP_INSTRUCTIONS` for the server-side setup prompt that tells Gemini
how to answer Job Logger support questions before the user's question is sent.
Do not put secrets, private URLs, or environment-specific credentials in that
prompt. The `/help/ask` route must require local authentication and a CSRF
header, cap submitted question and instruction length, send only bounded local
documentation/source context, call Gemini through its OpenAI-compatible
chat-completions API, build the final Gemini endpoint without duplicating the
`/chat/completions` suffix, and avoid any local database storage of prompts or
answers. The assistant may use source code as reference for user-facing app
behavior, but it must refuse source-code, deployment, secret, credential, or
internal configuration questions. Answer cleanup may trim a short dangling
fragment after a complete sentence, but it must not log answer text. Help page
operational-status cards must hide specific health issue details from ordinary
managed users and show those details only to Diagnostics-authorized users. AI
Help troubleshooting logs may include metadata such as trace ID, provider,
model, HTTP status, provider error code, input and answer lengths, context
source count, and elapsed time, but must not log Gemini API keys, raw questions,
prompts, provider request bodies, local source context, or answers.

## Audit Requirements

Important actions must record audit events through `job_logger/services/audit.py`.

Audit-worthy actions include:

- Authentication-sensitive events.
- Managed web-user add, edit, enable, disable, delete, archive, and restore actions.
- Per-user configuration updates.
- Managed web-user password changes.
- Managed web-user passkey registration, deletion, and login success/failure.
- Managed web-user session invalidation from Diagnostics.
- Job start.
- Job active edit save.
- First review client selection for an otherwise empty active job.
- Active job delete.
- Rounded start adjustment.
- Job end.
- Direct Work in Progress Autotask submission decision and outcome.
- Browser audio description recording events.
- Audio transcription.
- Review decisions and submitted-entry updates.
- AI summary cleanup requests.
- Accept/retry.
- Autotask submission attempts and outcomes.
- Successful Autotask submission activity.
- Debug Autotask API tests.
- Full backup downloads, automatic backup creation, and full restores.
- Delete time entry, delete note, or other destructive cleanup.

Do not include secrets, raw headers, raw audio, or excessive user text in audit
details.
Browser summary-note autosaves through `/jobs/{job_id}/description/text`
intentionally do not create `job.description.browser_text_saved` activity
events. Review autosaves intentionally do not create `job.review.saved`
activity events. Legacy copies of both low-value event types stay hidden from
the Review audit timeline without being deleted from the database.

## AI Summary Cleanup

AI cleanup is a data-sharing feature. It must remain disabled unless
`AI_CLEANUP_ENABLED=true` is configured with `AI_CLEANUP_PROVIDER=gemini`,
`grok`, `ollama`, or `lm_studio`. Gemini and Groq require matching provider API
keys. Ollama and LM Studio must use loopback or private-network base URLs such
as `localhost`, `127.0.0.1`, `host.docker.internal`, `10.x.x.x`,
`172.16-31.x.x`, or `192.168.x.x`.

Cleanup handling must:

- Require authentication and CSRF.
- Keep provider credentials, private-network provider URLs, and cleanup instructions
  server-side in Docker or another approved secret store.
- Send only bounded summary text and minimal job context to the selected
  provider.
- Use `GEMINI_API_BASE` for Gemini cleanup endpoint construction while keeping
  `GEMINI_CLEANUP_MODEL` separate from the Help model.
- Send configured cleanup instructions through the provider instruction field
  without using `AI_HELP_INSTRUCTIONS` or duplicating those private rules in
  the user-visible summary prompt.
- Reject public Ollama and LM Studio base URLs.
- Return cleaned text to the browser without submitting to Autotask.
- Audit provider, model, source, status, and text lengths only.
- Never write raw uncleaned summaries, cleaned summaries, API keys, or full
  provider payloads into audit events, logs, diagnostics, or templates.
- Store pre-cleanup summary text only on the owning job for the explicit
  **Revert cleanup** workflow, never in audit details or diagnostics. Clear the
  stored undo text after the user reverts cleanup or the cleaned summary is
  successfully finalized in Autotask. Also clear stale undo text after
  `AI_CLEANUP_REVERT_RETENTION_HOURS`, defaulting to 24 hours, so customer/work
  text is not retained indefinitely for an unused undo action.

Gemini's free API tier may use submitted content and generated responses to
improve Google products. GroqCloud does not retain inference customer data by
default except for platform reliability or abuse-monitoring cases, and its
Zero Data Retention setting should be enabled for the organization when
available. Ollama and LM Studio keep inference inside the configured private
network only when their API servers are not exposed beyond trusted LAN or
loopback interfaces.

## Raw Audio And Streaming

Raw audio must not be permanently stored by default.

Audio stream or compatibility upload handling must:

- Require authentication.
- Require CSRF validation before accepting audio bytes. WebSocket streams send
  the CSRF token in the first JSON message instead of the URL so reverse-proxy
  access logs do not capture it.
- Allow recording only for active jobs or review jobs that have not been
  successfully submitted to Autotask; submitted entries must reject later audio
  transcript changes server-side.
- Check content type.
- Enforce maximum audio size.
- Pass bytes to the transcription provider without writing persistent raw audio.
- When `TRANSCRIPTION_PROVIDER=faster_whisper_remote`, send audio only to the
  configured trusted transcription endpoint. HTTP endpoints must resolve to
  loopback or private-network hosts; public remote transcription endpoints must
  use HTTPS. Keep `FASTER_WHISPER_REMOTE_API_KEY` out of source control,
  templates, logs, and diagnostics.

If raw audio retention is ever added, it must be explicit, configurable,
documented, access-controlled, and auditable.

## PWA And Browser Storage

The web app manifest and icons are public app-shell metadata and must not
contain tenant, user, Autotask, or credential data.
Source logo assets and palette references belong in `docs/design/`. The
palette reference is documentation only; do not expose private deployment data
through app-shell icon assets.

The root-scoped service worker exists only so mobile devices can launch Job
Logger in standalone app mode. It must remain network-only and must not cache
authenticated pages, session-bound responses, job records, Autotask lookup
results, transcription responses, raw audio, CSRF tokens, or diagnostic output.

## Autotask Safety

Autotask failures should produce safe user-facing messages and troubleshooting
tips. Do not expose protocol details, headers, credentials, or full raw payloads.

The initial mobile page and blank Start Work route must not run Autotask
contactability checks. This keeps the mobile screen responsive and lets the
operator begin local work even if provider data is slow. Server-side validation
still applies when a workflow actually uses Autotask data, including service
call starts, company lookup, ticket selection, direct Work in Progress
submission, review submission, submitted-entry edit, and submitted-entry delete.
The debug API test must remain a fresh live diagnostic check.

Service-call starts and open-ticket selection may query Autotask for verified
metadata, but they must not patch Autotask ticket status or perform another
remote write. They only store local job metadata and default the editable local
ticket status to In progress until the time entry or ticket note is submitted.

Review detail may save a first client/company selection only when an active job
has no client name, company ID, or ticket number yet. That route must require
managed-user authentication, CSRF, job ownership, provider verification that
the submitted display name matches the selected Autotask company ID, and an
audit event. Typed-only client names, missing company IDs, and mismatched names
must be rejected without persistence. Review client search must not reuse the
generic review autosave path because typed search text is not trusted client
identity. Once any client/company/ticket identity exists, review
save/accept/ticket routes must continue to use the database row as authoritative
instead of trusting browser fields.
Active Work in Progress saves and end-work requests must also treat client
identity as a selected Autotask company before it can be saved or used for
ticket lookup. A saved Work in Progress client may be replaced by another
verified Autotask company until an open ticket is selected. After a ticket
exists, the database row is authoritative and crafted requests must not be able
to change the stored client name or attach a different company ID. Readonly
inputs and hidden client fields are only convenience values for normal form
flow after that ticket-selected lock.

Autotask ticket descriptions are remote provider data shown as read-only job
context. Store only the bounded description returned by the server-side verified
open-ticket lookup, render it escaped, and keep review save/accept handlers
from trusting browser-submitted description values.

Autotask ticket notes and past time entries are also remote provider data. The
shared overlay must load through authenticated server routes that enforce
review ownership rules, use the database ticket number, return bounded safe
fields, and render text through normal escaping or `textContent`. Keep note
list cards title-only, put safe author/date/type metadata in the selected note
detail, clamp long note-card titles to two visible lines, and show time-entry
resource/range metadata in list cards while keeping summary notes in the
selected detail pane. Do not expose raw Autotask responses, credentials, or
direct provider URLs to browser JavaScript.

Navigation destinations are sensitive location data. Store only bounded
single-line home and optional office values in the owning user's preference
row. Never include raw home, office, ticket, service-call, company-location, or
company-main addresses in audit details or application logs. Ticket and
service-call destinations must be resolved through authenticated, owner-checked
server routes and returned only as the one bounded address required for the
current launch. Do not store customer addresses on Job rows or expose raw
Autotask location records.

Autotask service-call starts must also be server verified. The mobile browser
may submit only the service-call ticket association ID and CSRF token; the
server must confirm the association is in today's service-call list for the
logged-in managed web user's Autotask resource ID before it creates a job or
stores any ticket/client details.

Successfully submitted Autotask jobs keep protected ticket/client identity,
entry type, and local audit history for the external Autotask record. The
server must reject later local review save, ticket selection, local delete,
accept/resend, retry, and entry-type conversion requests even if a crafted
request bypasses the review UI. This applies whether the external record was
created from Review acceptance or direct Work in Progress submission. The
allowed exception is the CSRF-protected **Submit changes** route. For submitted
time entries, it may update only job date, start time, end time, summary notes,
work location, append-to-resolution, and ticket status for the same submitted
job, and it must patch the existing Autotask `TimeEntries` row instead of
creating a new time entry. For submitted ticket notes, it may update only note
title, note description, append-to-resolution, and ticket status, and it must
patch the existing Autotask `TicketNotes` row instead of creating a new note.
If the previous ticket status was Complete, the provider may temporarily move
the ticket to In progress before the external-record patch and then apply the
selected final status. Submit changes must always reassert the selected local
ticket status in Autotask. A second CSRF-protected submitted action, **Delete
From Autotask**, may delete the external `TimeEntries` or `TicketNotes` row and
return the local job to review, but it must not delete the local job, audit
events, or submission attempts unless that remote delete fails and the user
confirms the session-scoped local-only purge fallback.

## Database And Deletion Safety

Jobs should not disappear silently.

Prefer retained workflow states over deletion. If destructive cleanup is
necessary, it must be explicit, authenticated, CSRF-protected, and auditable.
Review cleanup may delete local unsubmitted jobs, including active jobs, only
from the selected review detail through the explicit local delete action. The
mobile active-job delete route remains the quick in-progress discard path.
Local delete cleanup must stay blocked for successfully submitted Autotask jobs
so local history remains tied to the external Autotask record.
Submitted-entry corrections belong in the audited Submit changes or Delete From
Autotask routes, not local cleanup or resend flows. The only submitted-job local
cleanup exception is the explicit, CSRF-protected local-only purge offered after
Delete From Autotask fails, and it must warn that the Autotask entry may still
exist.

The `/debug` full backup and restore actions are the supported whole-app data
export/import path. They must remain limited to Diagnostics-authorized users
and CSRF-protected. Backup files contain all Job Logger database rows,
including managed web-user password hashes and customer/work history, and
should be treated as sensitive. Restore must validate backup format, version,
required tables, and expected columns before deleting current rows, must use the
application backup service instead of ad hoc shell commands, and must record a
post-restore audit event after the backup data has been restored. Narrow
backward-compatible defaults are allowed for newly added safe columns, such as
defaulting `user_preferences.submit_from_work_in_progress` to false when
restoring v1.0.2 backups. Failed confirmation, oversized upload, malformed
JSON, wrong format, or unsupported schema mismatch must leave current database
rows untouched.

Automatic backups use the same full-backup content format and restore path.
The scheduler writes one startup file and then hourly files under
`AUTOMATIC_BACKUP_DIR`, defaulting to `/data/backups` in Docker. Keep the
backup directory private: files must be written through owner-only temporary
files when possible. Swarm binds `/data/backups` to `backups/` under the
environment-specific `JOB_LOGGER_SWARM_STORAGE_PATH` shared NFS root. Retained
backups are available after task rescheduling,
directory listings and downloads must be Diagnostics-authorized only, selected
download or restore filenames must be strictly validated instead of trusting
form paths, and retention must purge expired automatic backups after successful
backup creation.
Creation audit details may include safe source metadata so `/debug` can label a
retained automatic backup as `Startup` or `Hourly`; do not infer or expose
sensitive runtime state for older files that lack that metadata.

## Docker And Runtime Safety

The application container runs as the fixed unprivileged `appuser` account.
Application, Nginx, and `cloudflared` operational logs must go only to
stdout/stderr so Compose and Swarm collect them through the container runtime.
Do not restore `LOG_DIR`, Nginx file-log paths, or the `cloudflared --logfile`
option.

PostgreSQL data must live in a persistent volume or documented persistent
storage.
PostgreSQL container health checks must be tolerant of first-time volume
initialization on slower Docker hosts. Add a startup grace period instead of
forcing operators to remove volumes when the database is merely still
bootstrapping.
Do not make Compose or Portainer stack creation depend on PostgreSQL becoming
healthy. Compose must also support remote PostgreSQL by keeping the bundled
PostgreSQL service behind `COMPOSE_PROFILES=local-db` and by letting
`DATABASE_URL` point at the remote server when that profile is disabled.
Compose must keep the bundled nginx and `cloudflared` services behind the
shared `bundled-edge` profile so they can be enabled or omitted together.
Normalize plain `postgresql://` and `postgres://` URLs to the installed psycopg
3 driver before creating app or Alembic engines. Keep remote database
connections bounded with the documented pool and timeout settings.
Swarm deployment must use prebuilt private GHCR images, a remote PostgreSQL
`DATABASE_URL`, and overlay networking. Production uses `docker-stack.yml`,
`jlapp`, `jlnginx`, production-tag image variable values, and
`http://jlnginx:<HTTP_PORT>`. Dev uses `docker-stack.dev.yml`, `jldapp`,
`jldnginx`, dev-tag values in the same per-stack image variables, and
`http://jldnginx:<HTTP_PORT>`.
`HTTP_PORT` controls the private Nginx listener and defaults to `80`; do not
publish it through the Swarm routing mesh because that would expose Nginx on
node interfaces. Run two `cloudflared` replicas per stack with
`max_replicas_per_node: 1`. Per-stack `JOB_LOGGER_SWARM_STORAGE_PATH` defaults
to `/mnt/swarm-storage/job-logger` in production and
`/mnt/swarm-storage/job-logger-dev` in dev. Both are already mounted on every
node and must hold only automatic backups and the faster-whisper model cache.
Do not run deployment-time `chown` or `chmod`, and do not add a PostgreSQL
service unless the operator explicitly requests a separate persistent Swarm
database design.

The app entrypoint should wait briefly for database connectivity and emit
sanitized diagnostics before migrations. If the database remains unavailable,
the web process must still start in temporary-service mode. DB-backed browser
routes should return an app-styled **Service Temporarily Unavailable** page
that auto-refreshes `/login` and does not expose database, network, code,
stack, or credential details. API-style requests should receive only a generic
503 body.

The internet-facing nginx template must expose only the web interface and the
authenticated browser actions required by those pages. Keep API-style,
generated schema/documentation, and public health paths blocked at nginx:
`/api`, `/openapi.json`, `/docs`, `/redoc`, `/nginx-health`, and `/health/*`.
Container health checks should use private Docker networking instead. Common
nginx-generated 4xx and 5xx responses should use internal app-styled Job Logger
web service error pages and must not expose stock server branding. Full restore
uploads may have a larger nginx body limit, but that limit must stay scoped to
`/debug/restore`.
Browser navigation to app-generated HTTP errors, including missing FastAPI
routes, should also render app-styled Job Logger error pages. Those pages must
derive the **Back to Login** or **Back to Work** action from the current signed
app session, and JSON/API clients that explicitly request JSON should keep
receiving JSON error bodies.

Cloudflare Tunnel tokens, Cloudflare API tokens, and app secrets must remain
outside source control. Docker Compose must not provide working default app,
database, or session secrets. Docker Compose should default
`CLOUDFLARE_ACCESS_REQUIRED=true` for internet-facing deployments, but
production startup must not hard-require that optional Access header gate.
Production startup must still fail unless `APP_SESSION_COOKIE_SECURE=true`,
non-default app/database secrets that are not copied placeholders are
configured, and `AUTOTASK_PROVIDER=autotask` is used.
Docker Compose Nginx publishing binds only to `127.0.0.1` and uses `HTTP_PORT`
as the host-networked `cloudflared` origin URL port. Swarm uses `HTTP_PORT` only
as Nginx's private overlay listener and does not publish it. External nginx
deployments must attach to the same trusted Docker network or Swarm overlay as
the app service
and mirror the bundled nginx security behavior: blocked API/schema/docs/health
paths, sanitized `X-Forwarded-For` and `X-Real-IP`, forwarded HTTPS scheme
preservation, the audio WebSocket route, the scoped `/debug/restore` body
limit, and app-styled proxy error pages. Use
`docs/external-nginx-job-logger.conf` as the maintained sample. The Cloudflare
Tunnel public hostname should be recorded through `WEBAUTHN_ORIGIN` when the
app needs the browser-facing URL, especially for passkeys.

## Tests To Consider

Security-sensitive changes usually need tests in:

- `tests/test_security.py`.
- `tests/test_passkeys.py`.
- `tests/test_workflow.py`.
- `tests/test_debug.py`.
- `tests/test_changelog.py` when version or release-history display changes.
- `tests/test_help.py` when Help navigation or help assistant behavior changes.

When in doubt, add a regression test for the security boundary being changed.
