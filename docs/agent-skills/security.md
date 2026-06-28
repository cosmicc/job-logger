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
selected from that resource's active Autotask roles, last successful login time,
Admin Diagnostics access, and disabled state.
Disabled web users must be blocked from new logins and from old signed sessions.
Managed-user passwords must be at least 8 characters and include lowercase,
uppercase, number, and symbol characters. Enforce that rule server-side before
hashing; browser validation is only a usability aid.

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

Managed web-user passkeys are optional login credentials. The config super
admin must not register or use passkeys. Passkey registration is available only
after a normal managed-user login from `/config`; login remains available from
the password page through a separate passkey button above the username/password
form. Failed, canceled, or unsupported passkey authentication must leave the
username/password form usable.
User-facing controls should call this feature **Device sign-in** even though the
technical implementation remains WebAuthn/passkeys. The `/home` device sign-in
setup card is only a one-time post-login prompt for managed users without a
passkey; `/config` must always keep the device sign-in setup action available.
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
The Diagnostics **Log out web users** action is CSRF-protected, audited, and
must invalidate only managed web-user sessions. It must not clear the current
config super-admin session. If a managed Admin user triggers it, that user is
included in the invalidation because the account is a managed web user.

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
navigation may show Users, Review, and Diagnostics icons; those links do not
grant any capability beyond the server-side authorization checks on the target
routes. Phone-sized managed-user navigation may show Home, Review, Config, and
Diagnostics only when `web_users.is_admin` is enabled. Non-admin managed users
must not show Diag or Diagnostics navigation. Phone-sized logout controls must
submit the normal CSRF-protected `/logout` form rather than using browser-only
close behavior.
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
Access JWTs. The visible `client_ip` is diagnostics-only. In the bundled Docker
path, nginx must overwrite forwarded client headers with a single sanitized
Cloudflare Tunnel client IP, preferring `CF-Connecting-IP` and falling back to
the direct nginx peer. Local login lockout and automatic Cloudflare block
decisions must use the trusted enforcement IP from nginx-sanitized
`X-Real-IP`/`X-Forwarded-For`, falling back to the direct app socket peer only
outside the bundled proxy path. Retain direct socket and proxy headers as
supporting metadata only. Failed-login rows may be hidden from the `/debug`
table by storing their raw-line hash in `hidden_login_failures`; never edit or
truncate the raw JSONL audit download. `login_failure_counters` stores
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
authentication method. Near the bottom of `/debug`, the page may show a
sanitized newest-first tail of `${LOG_DIR}/app.log`; keep that bounded to the
newest 10 displayed lines and redacted. Login failure, Cloudflare blocked-IP,
and Autotask submission-attempt diagnostics must stay paginated at 10 rows per
page. Wide Diagnostics tables should stay horizontally scrollable on phone
layouts instead of compressing columns, especially when they include per-row
backup or Cloudflare actions. `LOG_LEVEL` controls app-log verbosity and must
be limited to `DEBUG`, `INFO`, `WARNING`, or `ERROR`. `/debug` may also show
disk usage for
app-visible storage paths such as `/`, `${LOG_DIR}`, and
`${AUTOMATIC_BACKUP_DIR}`. Combine monitored paths when used bytes and total
bytes match exactly, and keep disk diagnostics read-only and limited to path,
usage, and warning/critical metadata.
`DEV_BUILD=true` is a display-only runtime marker for the authenticated header;
do not use it as an authorization, environment-isolation, or safety boundary.

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
- Managed web-user add, edit, enable, disable, and delete-as-disable actions.
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
ticket lookup, and as locked after either an Autotask company or open ticket is
selected. Readonly inputs and hidden client fields are only convenience values
for normal form flow; crafted requests must not be able to change the stored
client name or attach a different company ID after a ticket exists.

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
submission. The allowed exception is the CSRF-protected **Submit changes** route,
which may update only job date, start time, end time, summary notes, work
location, and ticket status for the same submitted job. It must patch the
existing Autotask `TimeEntries` row instead of creating a new time entry. If the
previous ticket status was Complete, the provider may temporarily move the
ticket to In progress before the time-entry patch and then apply the selected
final status. Submit changes must always reassert the selected local ticket
status in Autotask. A second
CSRF-protected submitted action, **Delete From Autotask**, may delete the
external `TimeEntries` row and return the local job to review, but it must not
delete the local job, audit events, or submission attempts unless that remote
delete fails and the user confirms the session-scoped local-only purge fallback.

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
`AUTOMATIC_BACKUP_DIR`, defaulting to a host-mounted runtime backup directory in
Docker. Keep the backup directory
private: files must be written through owner-only temporary files when possible,
directory listings and downloads must be Diagnostics-authorized only, selected
download or restore filenames must be strictly validated instead of trusting
form paths, and retention must purge expired automatic backups after successful
backup creation.
Creation audit details may include safe source metadata so `/debug` can label a
retained automatic backup as `Startup` or `Hourly`; do not infer or expose
sensitive runtime state for older files that lack that metadata.

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

Cloudflare Tunnel tokens, Cloudflare API tokens, and app secrets must remain
outside source control. Docker Compose must not provide working default app,
database, or session secrets. Docker Compose should default
`CLOUDFLARE_ACCESS_REQUIRED=true` for internet-facing deployments, but
production startup must not hard-require that optional Access header gate.
Production startup must still fail unless `APP_SESSION_COOKIE_SECURE=true`,
non-default app/database secrets that are not copied placeholders are
configured, and `AUTOTASK_PROVIDER=autotask` is used.
Docker nginx publishing uses `BIND_ADDRESS` plus `HTTP_PORT`, with
`NGINX_PUBLIC_PORT` retained only as a compatibility fallback; the default bind
is `127.0.0.1` and the bundled host-networked `cloudflared` connector should
target the same loopback origin URL.

## Tests To Consider

Security-sensitive changes usually need tests in:

- `tests/test_security.py`.
- `tests/test_passkeys.py`.
- `tests/test_workflow.py`.
- `tests/test_debug.py`.
- `tests/test_changelog.py` when version or release-history display changes.

When in doubt, add a regression test for the security boundary being changed.
