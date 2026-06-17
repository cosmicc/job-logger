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

Authentication routes live in `job_logger/routes/auth.py`.

Application setup in `job_logger/main.py` configures:

- Signed server-side session cookie behavior through Starlette sessions.
- Trusted host filtering when configured.
- Optional Cloudflare Access header enforcement.
- Security headers and Content Security Policy.

Production must not use default secrets or missing passwords.

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
- Session secrets.
- Database passwords.
- Cloudflare tunnel tokens.
- Cloudflare Access JWTs.
- Raw authentication headers.
- Raw audio.

Diagnostic pages and audit details must use safe summaries only.

## Audit Requirements

Important actions must record audit events through `job_logger/services/audit.py`.

Audit-worthy actions include:

- Authentication-sensitive events.
- Job start blocked because Autotask is unavailable.
- Job start.
- Job active edit save.
- Active job delete.
- Rounded start adjustment.
- Job end.
- Description text save.
- Audio transcription.
- Manual review save.
- Accept/retry/reject.
- Autotask submission attempts and outcomes.
- Debug Autotask API tests.
- Force purge or other destructive cleanup.

Do not include secrets, raw headers, raw audio, or excessive user text in audit
details.

## Raw Audio And Uploads

Raw audio must not be permanently stored by default.

Audio upload handling must:

- Require authentication.
- Require CSRF header validation.
- Check content type.
- Enforce maximum upload size.
- Pass bytes to the transcription provider without writing persistent raw audio.

If raw audio retention is ever added, it must be explicit, configurable,
documented, access-controlled, and auditable.

## Autotask Safety

Autotask failures should produce safe user-facing messages and troubleshooting
tips. Do not expose protocol details, headers, credentials, or full raw payloads.

Autotask API availability gates new job starts because production workflow
depends on company and ticket data.

## Database And Deletion Safety

Jobs should not disappear silently.

Prefer retained workflow states over deletion. If destructive cleanup is
necessary, it must be explicit, authenticated, CSRF-protected, and auditable.
Review cleanup must stay blocked for active jobs. The mobile active-job delete
route is the reviewed exception for discarding an in-progress entry before it
becomes review history, and it must not be reused for completed jobs.

## Docker And Runtime Safety

The application container should not run as root unless explicitly documented.

PostgreSQL data must live in a persistent volume or documented persistent
storage.

Cloudflare Tunnel tokens and app secrets must remain outside source control.

## Tests To Consider

Security-sensitive changes usually need tests in:

- `tests/test_security.py`.
- `tests/test_workflow.py`.
- `tests/test_debug.py`.

When in doubt, add a regression test for the security boundary being changed.
