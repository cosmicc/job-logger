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
passkey routes live in `job_logger/routes/passkeys.py`.

`APP_USERNAME` and `APP_PASSWORD` authenticate only the config super admin. That
account can manage `/users`, view all review jobs, use diagnostics, and run
backup/restore, but it must not start, edit, submit, delete, record, or
AI-cleanup jobs because it has no Autotask resource ID. Work-entry users are
database-managed `WebUser` rows created on `/users`; they store full name,
username, salted password hash, required Autotask resource ID, optional email
captured from Autotask Resource lookup, optional default service-desk role ID
selected from that resource's active Autotask roles, and disabled state.
Disabled web users
must be blocked from new logins and from old signed sessions. Managed-user
passwords must be at least 8 characters and include lowercase, uppercase,
number, and symbol characters. Enforce that rule server-side before hashing;
browser validation is only a usability aid.

Local authenticated sessions must expire after `APP_SESSION_TIMEOUT_HOURS`.
`job_logger/session_timeout.py` enforces the server-side timestamp check, and
Starlette session cookies use the same configured lifetime. Every successful
password or passkey login must stamp the session with the authentication time
and method so stale signed cookies cannot remain valid past the configured
timeout.
Managed web-user sessions can also be invalidated by a per-user UTC cutoff in
the `web_users` row. `job_logger/services/session_control.py` owns that cutoff
logic. Disabling one user or using the Diagnostics **Log out web users** action
must clear old managed-user cookies on the next request without signing out the
config super admin.

Managed web-user passkeys are optional login credentials. The config super
admin must not register or use passkeys. Passkey registration is available only
after a normal managed-user login from `/config`; login remains available from
the password page through a separate passkey button. Failed, canceled, or
unsupported passkey authentication must leave the username/password form usable.
The `/home` Add Passkey card is only a one-time post-login prompt for managed
users without a passkey; `/config` must always keep the Add Passkey action
available.

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

The `/debug` page and all `/debug/*` actions are config-super-admin-only.
Normal managed web users must not see a Debug navigation item, and direct
requests from managed web-user sessions must receive 403 instead of being
treated as anonymous login redirects.
The Diagnostics **Log out web users** action is CSRF-protected, audited, and
must invalidate only managed web-user sessions. It must not clear the current
config super-admin session.

The `/users/autotask-resources` lookup endpoint is super-admin-only and must
return only safe Autotask Resource metadata. Browser code can use it from
add/edit user forms to fill the resource ID field, but the server must still
validate the submitted resource ID and must never expose Autotask credentials or
raw remote error details.
The `/users/autotask-resource-roles` lookup endpoint is also super-admin-only.
It may return active `ResourceServiceDeskRoles.roleID` values and safe display
labels for the selected resource, but saving a submitted default role must still
re-query the server-side provider and verify that role is active for the
submitted resource ID.
The per-row `/users/{user_id}/refresh-resource` action is also
super-admin-only, CSRF-protected, and must update only safe local metadata after
matching the returned Autotask resource ID to the user's stored ID.

Per-user configuration lives behind authenticated managed-web-user-only
`/config` routes. The config super admin has no user settings, must not see the
Config menu item or phone-sized Config icon, must receive 403 on direct
`/config` access, and always renders in dark mode. Phone-sized super-admin
navigation may show Users, Review, and Diagnostics icons; those links do not
grant any capability beyond the server-side authorization checks on the target
routes. Phone-sized managed-user navigation may show Home, Review, and Config,
but must not show Debug. Phone-sized logout controls must submit the normal
CSRF-protected `/logout` form rather than using browser-only close behavior.
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
requirements so users can fix validation failures before submitting. Never log,
audit, or flash the raw submitted password.

Deleting a managed web user from `/users` must disable the account, invalidate
that user's existing signed sessions, and preserve the row. Keeping the row lets
the login screen explain that the account is disabled after the correct
password is submitted instead of treating the username as unknown.

Application setup in `job_logger/main.py` configures:

- Signed server-side session cookie behavior through Starlette sessions.
- Server-side session timeout checks through `SessionTimeoutMiddleware`.
- Trusted host filtering when configured.
- Optional Cloudflare Access header enforcement.
- Security headers and Content Security Policy.

Production must not use default secrets or missing passwords.

Successful and failed local app login attempts are recorded in configured JSONL
files, defaulting to `${LOG_DIR}/job-logger-login-successes.log` and
`${LOG_DIR}/job-logger-login-failures.log`. Docker Compose sets
`LOG_DIR=/data/logs` and bind-mounts `HOST_LOG_DIR=/var/log/job-logger` there
so operators can read log files from the Docker host. The login logs and
`/debug` login windows may show timestamp, client IP details, submitted
username, account kind, authentication method, username length/truncation for
failures, user agent, request path, host/proxy metadata, reason, and
password-present/length metadata for failures. They must never include the raw
submitted password, session tokens, authentication headers, or Cloudflare
Access JWTs. When `X-Forwarded-For` is present, the first forwarded address is
the display `client_ip` for login diagnostics; retain the direct socket peer
and other proxy headers as supporting metadata only. The successful-login table
may use a yellow account-kind chip for config super-admin rows so they are easy
to distinguish from managed web users. The bottom of `/debug` may show a
sanitized newest-first tail of `${LOG_DIR}/app.log`; keep that bounded,
scrollable, and redacted. `/debug` may also show disk usage for app-visible
storage paths such as `/`, `${LOG_DIR}`, and `${AUTOMATIC_BACKUP_DIR}`. Keep
disk diagnostics read-only and limited to path, usage, and warning/critical
metadata.

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
- Raw authentication headers.
- Raw audio.

Diagnostic pages and audit details must use safe summaries only.
Authenticated pages may show the source-controlled application version because
it is non-secret build metadata; do not source that value from environment
variables that could drift between containers. Keep `/changelog` authenticated
so release history stays inside the app shell even though it contains only
source-controlled release notes. The web changelog must come from concise
`WEB_CHANGELOG.md` entries, while `CHANGELOG.md` remains the detailed
operator/agent release record.

## Audit Requirements

Important actions must record audit events through `job_logger/services/audit.py`.

Audit-worthy actions include:

- Authentication-sensitive events.
- Managed web-user add, edit, enable, disable, delete-as-disable, and
  Autotask Resource metadata refresh actions.
- Per-user configuration updates.
- Managed web-user password changes.
- Managed web-user passkey registration, deletion, and login success/failure.
- Managed web-user session invalidation from Diagnostics.
- Job start.
- Job active edit save.
- Active job delete.
- Rounded start adjustment.
- Job end.
- Direct Work in Progress Autotask submission decision and outcome.
- Description text save.
- Audio transcription.
- Manual review save.
- AI summary cleanup requests.
- Accept/retry.
- Autotask submission attempts and outcomes.
- Debug Autotask API tests.
- Full backup downloads, automatic backup creation, and full restores.
- Delete time entry or other destructive cleanup.

Do not include secrets, raw headers, raw audio, or excessive user text in audit
details.

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
- Set `store=false` on Gemini generateContent requests.
- Send configured cleanup instructions through the provider instruction field
  without duplicating those private rules in the user-visible summary prompt.
- Reject public Ollama and LM Studio base URLs.
- Return cleaned text to the browser without submitting to Autotask.
- Audit provider, model, source, status, and text lengths only.
- Never write raw uncleaned summaries, cleaned summaries, API keys, or full
  provider payloads into audit events, logs, diagnostics, or templates.

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

If raw audio retention is ever added, it must be explicit, configurable,
documented, access-controlled, and auditable.

## PWA And Browser Storage

The web app manifest and icons are public app-shell metadata and must not
contain tenant, user, Autotask, or credential data.

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
ticket status to In progress until the time entry is submitted.

Autotask ticket descriptions are remote provider data shown as read-only job
context. Store only the bounded description returned by the server-side verified
open-ticket lookup, render it escaped, and keep review save/accept handlers
from trusting browser-submitted description values.

Autotask service-call starts must also be server verified. The mobile browser
may submit only the service-call ticket association ID and CSRF token; the
server must confirm the association is in today's service-call list for the
logged-in managed web user's Autotask resource ID before it creates a job or
stores any ticket/client details.

Successfully submitted Autotask jobs keep protected ticket/client identity and
local audit history for the external time entry. The server must reject later
local review save, ticket selection, local delete, accept/resend, and retry
requests even if a crafted request bypasses the review UI. This applies whether
the external entry was created from Review acceptance or direct Work in Progress
submission. The allowed exception is the CSRF-protected **Edit Entry** route,
which may update only job date, start time, end time, summary notes, and ticket
status for the same submitted job. It must patch the existing Autotask
`TimeEntries` row instead of creating a new time entry. If the previous ticket
status was Complete, the provider may temporarily move the ticket to In progress
before the time-entry patch and then apply the selected final status. A second
CSRF-protected submitted action, **Delete From Autotask**, may delete the
external `TimeEntries` row and return the local job to review, but it must not
delete the local job, audit events, or submission attempts.

## Database And Deletion Safety

Jobs should not disappear silently.

Prefer retained workflow states over deletion. If destructive cleanup is
necessary, it must be explicit, authenticated, CSRF-protected, and auditable.
Review cleanup may delete local unsubmitted jobs, including active jobs, only
from the selected review detail through the explicit **Delete time entry**
action. The mobile active-job delete route remains the quick in-progress
discard path. Local **Delete time entry** cleanup must stay blocked for
successfully submitted Autotask jobs so local history remains tied to the
external time entry.
Submitted-entry corrections belong in the audited Edit Entry or Delete From
Autotask routes, not local cleanup or resend flows.

The `/debug` full backup and restore actions are the supported whole-app data
export/import path. They must remain super-admin-only and CSRF-protected. Backup
files contain all Job Logger database rows, including managed web-user password
hashes and customer/work history, and should be treated as sensitive. Restore
must validate backup format, version, required tables, and expected columns
before deleting current rows, must use the application backup service instead
of ad hoc shell commands, and must record a post-restore audit event after the
backup data has been restored. Narrow backward-compatible defaults are allowed
for newly added safe columns, such as defaulting
`user_preferences.submit_from_work_in_progress` to false when restoring v1.0.2
backups. Failed confirmation, oversized upload, malformed JSON, wrong format,
or unsupported schema mismatch must leave current database rows untouched.

Automatic backups use the same full-backup content format and restore path.
The scheduler writes hourly files under `AUTOMATIC_BACKUP_DIR`, defaulting to a
host-mounted runtime backup directory in Docker. Keep the backup directory
private: files must be written through owner-only temporary files when possible,
directory listings must be super-admin-only, selected restore filenames must be
strictly validated instead of trusting form paths, and retention must purge
expired automatic backups after successful backup creation.

## Docker And Runtime Safety

The application container starts as root only long enough to prepare
host-mounted log paths, then runs migrations and Uvicorn as the fixed
unprivileged `appuser` account.

PostgreSQL data must live in a persistent volume or documented persistent
storage.
PostgreSQL container health checks must be tolerant of first-time volume
initialization on slower Docker hosts. Add a startup grace period instead of
forcing operators to remove volumes when the database is merely still
bootstrapping.
Do not make Compose or Portainer stack creation depend on PostgreSQL becoming
healthy. Preserve start order, then let the app entrypoint wait for database
connectivity and emit sanitized diagnostics before migrations.

The internet-facing nginx template must expose only the web interface and the
authenticated browser actions required by those pages. Keep API-style,
generated schema/documentation, and public health paths blocked at nginx:
`/api`, `/openapi.json`, `/docs`, `/redoc`, `/nginx-health`, and `/health/*`.
Container health checks should use private Docker networking instead. Full
restore uploads may have a larger nginx body limit, but that limit must stay
scoped to `/debug/restore`.

Cloudflare Tunnel tokens and app secrets must remain outside source control.

## Tests To Consider

Security-sensitive changes usually need tests in:

- `tests/test_security.py`.
- `tests/test_passkeys.py`.
- `tests/test_workflow.py`.
- `tests/test_debug.py`.
- `tests/test_changelog.py` when version or release-history display changes.

When in doubt, add a regression test for the security boundary being changed.
