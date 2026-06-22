# Job Logger

Job Logger is a security-focused Dockerized Python web application for quickly
recording work time from a phone, reviewing or directly submitting recorded
jobs, and sending accepted work to Autotask.

## Architecture

- FastAPI serves the application.
- Nginx fronts the FastAPI web interface inside Docker.
- Jinja templates render the mobile capture page, desktop review page, user
  manager, config page, and diagnostics.
- PostgreSQL stores managed web users, jobs, review fields, submission attempts,
  per-user preferences, and audit events.
- Alembic manages database migrations.
- Cloudflare Tunnel publishes the app without opening an inbound firewall port.
- Cloudflare Access can protect the public hostname before the app login page.
- Configurable providers support mock or live speech-to-text and Autotask modes.

Cloudflare documents Tunnel as an outbound `cloudflared` connector and Access as
the control point for self-hosted applications:

- https://developers.cloudflare.com/tunnel/setup/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/

Autotask REST API references used by this app:

- TimeEntries entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TimeEntriesEntity.htm
- Tickets entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketsEntity.htm
- Companies entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/CompaniesEntity.htm
- Resources entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ResourcesEntity.htm
- ResourceServiceDeskRoles entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ResourceServiceDeskRolesEntity.htm
- ServiceCalls entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallsEntity.htm
- ServiceCallTickets entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallTicketsEntity.htm
- ServiceCallTicketResources entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallTicketResourceEntity.htm
- REST authentication headers: https://www.autotask.net/help/developerhelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm

## Local Setup

1. Create an environment file:

   ```bash
   cp .env.example .env
   ```

2. Set `APP_USERNAME` and `APP_PASSWORD` in `.env`. This config account is the
   super admin for diagnostics and user management; it does not create work
   entries because it has no Autotask resource ID.

3. Replace `APP_SECRET_KEY` with a long random value.

4. Create the host-mounted log directory:

   ```bash
   sudo install -d -m 0750 /var/log/job-logger
   ```

   Docker Compose sets `LOG_DIR=/data/logs` inside the app container and
   mounts `${HOST_LOG_DIR:-/var/log/job-logger}` there. The entrypoint prepares
   ownership before it drops to the unprivileged `appuser`.

5. Start the stack:

   ```bash
   docker compose up -d --build
   ```

   If you do not have a tunnel token yet, run only local services first:

   ```bash
   docker compose up -d --build app db nginx
   ```

6. Open the local troubleshooting URL at:

   ```text
   http://127.0.0.1:11030
   ```

7. Sign in with the config super-admin account, open `/users`, and create at
   least one web user with full name, username, password, and Autotask resource
   ID. The users page shows managed accounts in a table with per-row edit,
   refresh, enable/disable, and disable controls as compact icons, including any
   email address captured from Autotask Resource lookup. The disable action signs
   out that user's existing sessions on their next request and blocks future
   login. The refresh icon re-queries Autotask Resources and updates the stored
   local name/email metadata when the returned resource still matches that user's
   saved resource ID. The
   add-user form suggests a username from the name, such as `jblow` for
   `Joe Blow`, and add/edit forms can search Autotask Resources so you can
   select the matching `Last, First` resource and fill its ID. The same form can
   load active service-desk roles for that resource and save an optional default
   role fallback for tickets that do not return usable role data. When Autotask
   returns an email for the selected resource, Job Logger saves it with that
   web-user account. Managed-user passwords must be at least 8 characters and
   include lowercase, uppercase, number, and symbol characters. The first web
   user you create takes ownership of any existing unowned jobs from earlier
   single-user installs.

8. Managed web users can open `/config` to choose their visual theme and work
   completion behavior. Dark is the default, and changes save and apply
   immediately without a Save button. Light and dark themes apply to mobile and
   web pages for that login only. The **Submit from Work in Progress** workflow
   option is off by default; when enabled, ending work submits the time entry to
   Autotask immediately instead of requiring Review first. The same page
   includes an explicit **Change password** action with two matching password
   fields and the password requirements shown in the password card; password
   changes are not autosaved. Managed users can also add passkeys after signing
   in normally once. The config super-admin account has no user settings and
   always uses dark mode.

## Branch And Deployment Flow

`main` is the production branch. Production deployments should pull from
`main` only after changes have already been tested and intentionally merged.

`dev` is the integration and testing branch. It was created as a copy of the
current `main` branch and is intended for a separate dev instance where changes
can be tested before they are merged back to `main`.

For a dev deployment, use a separate checkout or working tree on the server:

```bash
git clone --branch dev https://github.com/cosmicc/job-logger.git job-logger-dev
```

Keep the dev instance isolated from production:

- Use a separate `.env` with its own `APP_SECRET_KEY`, database password,
  Cloudflare tunnel token, allowed hostname, and WebAuthn origin.
- Use a separate Cloudflare Tunnel and public hostname for dev testing.
- Use a separate Docker Compose project name, PostgreSQL volume, backup
  directory, and host log directory so dev cannot overwrite production data.
- Use a different `NGINX_PUBLIC_PORT`, such as `11031`, if production and dev
  run on the same Docker host.
- Use real Autotask credentials only when the dev workflow intentionally needs
  live Autotask testing. Keep `AUTOTASK_PROVIDER=mock` for isolated UI or
  workflow-only checks.

Example same-host dev startup:

```bash
COMPOSE_PROJECT_NAME=job_logger_dev \
HOST_LOG_DIR=/var/log/job-logger-dev \
NGINX_PUBLIC_PORT=11031 \
docker compose up -d --build
```

Do not merge `dev` into `main` until the dev instance has passed the intended
validation and a production release is ready.

## Cloudflare Tunnel

The Compose file starts Nginx and `cloudflared` by default. This keeps the
production deployment path simple: the app, PostgreSQL, Nginx reverse proxy, and
tunnel connector all come up with one `docker compose up -d --build` command.

1. Create a Cloudflare Tunnel in the Zero Trust dashboard.
2. Add a public hostname that routes to this Docker service URL:

   ```text
   http://127.0.0.1:11030
   ```

   The Compose-managed `cloudflared` service uses host networking, so
   `127.0.0.1` is the stable address from the connector to the host-published
   Nginx port. Avoid using a Wi-Fi or LAN address unless `cloudflared` is
   running on a different host, because those addresses can change and produce
   Cloudflare 502 errors.

3. Optionally create a Cloudflare Access self-hosted application for that hostname.
4. Put the same hostname in `.env` under `APP_ALLOWED_HOSTS`.
5. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
   If this token is missing or invalid, Cloudflare will return a 502 and
   `cloudflared` will repeatedly restart.
6. Leave `CLOUDFLARE_ACCESS_REQUIRED=false` when using only the app's
   `APP_USERNAME` and `APP_PASSWORD` login. Set it to `true` only after
   Cloudflare Access is configured and verified for the public hostname.
7. Set `WEBAUTHN_ORIGIN` to the public HTTPS origin that phones see in the
   browser, such as `https://logger.example.com`, before using passkeys through
   Cloudflare Tunnel. The bundled nginx origin also preserves Cloudflare's
   forwarded HTTPS scheme for WebAuthn, but this explicit setting is the safest
   production pin. Set `WEBAUTHN_RP_ID` to the same hostname if the app cannot
   reliably derive the public host from forwarded headers.
8. Start the full stack:

   ```bash
   docker compose up -d --build
   ```

   After changing `APP_ALLOWED_HOSTS`, `NGINX_PUBLIC_PORT`, or the nginx proxy
   config, recreate the app-facing services so Docker applies the new container
   environment and rendered nginx config:

   ```bash
   docker compose up -d --build --force-recreate app nginx cloudflared
   ```

Nginx is the web front end for this deployment. Public mobile and review
traffic should enter through the Cloudflare Tunnel hostname, reach the host-exposed
Nginx endpoint on `127.0.0.1:11030` from the Compose-managed connector by
default (or `127.0.0.1:<NGINX_PUBLIC_PORT>` after you change it), and then
proxy to FastAPI at `http://app:8000`.

The app container is exposed only to the private Compose network. The local
troubleshooting URL reaches Nginx on `127.0.0.1`, not the app container
directly.

Nginx binds `NGINX_PUBLIC_PORT` on host interfaces so the Compose-managed
tunnel can reach the origin through host networking. If you intentionally point
a remotely-managed tunnel at a LAN/server IP instead of `127.0.0.1`, keep host
firewall rules limited to trusted networks or the tunnel connector path because
direct LAN access to this port bypasses Cloudflare Access. Application login
still protects the app itself.

`NGINX_PUBLIC_PORT` is the only configurable host-facing port. All other service
ports are fixed internally and are not intended to be changed via environment:

- Nginx listens on container port `80`.
- App listens on container port `8000`.
- PostgreSQL stays internal to Compose on container port `5432`.

If the local troubleshooting URL is changed to a different port, update only:

```env
NGINX_PUBLIC_PORT=<your-host-port>
```

If `cloudflared` is not running in this Compose stack, it will not be able to
resolve the Docker service name `nginx`. In that separate-deployment case,
either move `cloudflared` into this Compose stack or point the tunnel at the
actual host-reachable Nginx URL.

Nginx is the public web edge and intentionally blocks API-style, generated
schema/documentation, and health-check paths such as `/api`, `/openapi.json`,
`/docs`, `/redoc`, `/nginx-health`, and `/health/*`. The Docker health checks
use private container networking instead of public URLs.

The nginx container is built from `docker/nginx/Dockerfile` with this app's
proxy template baked in. If blocked public paths do not return this app's nginx
response, the running container may not be using this project's image/config and
should be rebuilt.

The normal Nginx startup log ends with `Configuration complete; ready for start
up` and `start worker process`. If the log later says `signal 3 (SIGQUIT)
received, shutting down`, Docker or Compose asked Nginx to stop gracefully; that
line is not an Nginx configuration failure by itself.

### PostgreSQL Healthcheck Troubleshooting

If a first-time or cold Docker/Portainer deploy fails with a message like
`dependency failed to start: container job-logger-dev-db-1 is unhealthy`, check
the PostgreSQL container before removing any volumes:

```bash
docker ps -a --filter name=job-logger-dev-db-1
docker logs --tail=120 job-logger-dev-db-1
docker inspect --format '{{.State.Health.Status}}' job-logger-dev-db-1
```

The database service healthcheck has a startup grace period, and Compose starts
the app after the database container is started rather than aborting the stack
on the DB health status. The app entrypoint then waits for real database
connectivity before running migrations. If the DB container remains unhealthy,
treat it as a real database startup problem. The most common causes are a stale
dev stack volume with different PostgreSQL credentials, a damaged/incompatible
data directory, or an environment mismatch in the deployed stack.

For disposable dev stacks only, the fastest reset is to remove the failed dev
stack and its dev PostgreSQL volume, then redeploy with the intended `.env`.
Do not remove the production `postgres_data` volume unless the stored job
history is intentionally being discarded or a current backup has been verified.

### PostgreSQL Password Troubleshooting

The PostgreSQL Docker image only applies `POSTGRES_PASSWORD` when the database
volume is first initialized. If `.env` is changed later while keeping the same
`postgres_data` volume, the app can loop at startup with database retry messages
or PostgreSQL can log `password authentication failed for user "job_logger"`.

Do not delete the database volume to fix a password mismatch unless the stored
job history is intentionally being discarded. Instead, update the existing
PostgreSQL role password to match the current container environment:

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v database_user="$POSTGRES_USER" -v database_password="$POSTGRES_PASSWORD"' <<'SQL'
ALTER ROLE :"database_user" WITH PASSWORD :'database_password';
SQL
```

Then recreate the app container so migrations and FastAPI reconnect with the
current credentials:

```bash
docker compose up -d --build --force-recreate app nginx
```

### Tunnel 502 Troubleshooting

A Cloudflare 502 means the request reached Cloudflare and the tunnel connector,
but `cloudflared` could not reach the origin service configured for the public
hostname.

Check these items first:

- Confirm `.env` exists and contains a real `CLOUDFLARE_TUNNEL_TOKEN`.
- Confirm the Cloudflare tunnel origin (what your Cloudflare connector is configured
  to reach) is `http://127.0.0.1:11030` by default, or your configured
  `NGINX_PUBLIC_PORT`. If the tunnel is configured to a LAN address, verify that
  the address is still assigned to this host before looking for app problems.
- Confirm the public web path reaches the app login from the Docker host:

  ```bash
  curl -i http://127.0.0.1:11030/login
  ```

- Confirm the public health/API paths stay blocked at Nginx. These should
  return HTTP 404:

  ```bash
  curl -i http://127.0.0.1:11030/health/live
  curl -i http://127.0.0.1:11030/openapi.json
  ```

- Confirm Nginx is reachable through the same origin address used by Cloudflare:

  ```bash
  curl -i http://127.0.0.1:11030/login
  ```

- Confirm the app accepts the Cloudflare public hostname after container
  recreation:

  ```bash
  curl -i -H 'Host: joblogger.lsec.io' http://127.0.0.1:11030/login
  ```

- Confirm the app is healthy from inside the app container:

  ```bash
  docker compose exec app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"
  ```

- Review tunnel connector logs:

  ```bash
  docker compose logs --tail=100 cloudflared
  ```

- Confirm app-level host filtering is not rejecting the Cloudflare hostname:

  ```bash
  docker compose logs --tail=120 app | rg "Invalid host header|Invalid Host header|Cloudflare Access"
  ```

- Run the bundled tunnel diagnostic script:

  ```bash
  scripts/diagnose_tunnel.sh
  ```

The work-entry home route is `/home`. The app also redirects `/mobile` and
`/moble` to `/home` to preserve old bookmarks and avoid a common typo after the
tunnel is working.

## Mobile App Mode

Job Logger includes progressive web app metadata so a phone can install it from
the browser and launch it without the normal browser toolbar.

Use the Cloudflare HTTPS hostname on the phone, sign in, open the browser menu,
and choose the platform's install action such as **Add to Home Screen** or
**Install App**. After launching from that home-screen icon, the app uses
standalone display mode, the managed web user's saved page theme, safe-area
padding for phone status bars, and disabled page overscroll/bounce behavior.

The service worker is intentionally network-only. It supports standalone app
launch behavior but does not cache authenticated pages, job data, Autotask
responses, transcription data, raw audio, or diagnostics.
Static CSS and JavaScript links include a content-derived version value so
browser and installed-app shells fetch changed assets after deploy without
requiring an application version bump.

## Authentication And Passkeys

Local app sessions expire after `APP_SESSION_TIMEOUT_HOURS`, defaulting to
`12`. The value is measured in hours and is used for both the signed session
cookie lifetime and server-side login timestamp checks. After it expires, users
must sign in again.
The config super admin can also use Diagnostics to log out all managed web
users without ending the current super-admin session. Disabled managed web-user
accounts are signed out on their next request and, after the correct password is
submitted, the login screen says the account is disabled.

The config super-admin account still signs in with `APP_USERNAME` and
`APP_PASSWORD` only. Managed web users can sign in with their username/password
or with a registered passkey. A passkey can be added from `/config` after a
normal password login. The `/home` page prompts managed users without a passkey
only once after each successful login, while `/config` always keeps passkey
setup available. Job Logger stores only the public credential ID, public key,
signature counter, and device metadata. The phone, browser, or passkey provider
keeps the private key and performs the fingerprint, Face ID, PIN, pattern, or
other local unlock prompt.

Passkey login is intentionally a fallback-friendly option. If the browser does
not support passkeys, the device cancels, or signature verification fails, the
normal username/password login form remains available.

Set these passkey variables for production when needed:

- `WEBAUTHN_RP_NAME`, the label shown by the browser, defaults to `Job Logger`.
- `WEBAUTHN_RP_ID`, optional relying-party domain override, such as
  `logger.example.com`.
- `WEBAUTHN_ORIGIN`, optional expected browser origin, such as
  `https://logger.example.com`. Set this for Cloudflare Tunnel deployments as
  an explicit production pin; nginx also preserves the forwarded HTTPS scheme
  so the app can derive the correct origin when this is unset.

## Application Version And Changelog

Job Logger uses source-controlled semantic versioning. The runtime version is
defined in `job_logger/version.py`, mirrored in `pyproject.toml`, and is
currently `v1.1.1`. Version history starts at `v1.0.0`.

Authenticated pages show the current version discreetly in the shared header.
Clicking that version opens `/changelog`, which displays the current version
and concise release notes parsed from `WEB_CHANGELOG.md`. The current-version
panel lists short user-facing changes directly, and the timeline keeps prior
versions visible. `CHANGELOG.md` remains the detailed source changelog for
operators and agents. `WEB_CHANGELOG.md` is only for user-facing changes; keep
diagnostics, debug-page, super-admin-only, operator-only, and agent-facing notes
in `CHANGELOG.md` only. The changelog page uses the same authenticated session,
dark/light theme variables, and responsive layout system as the rest of the app.

## Provider Modes

### Speech To Text

`TRANSCRIPTION_PROVIDER=faster_whisper` uses the local faster-whisper package to
transcribe job notes inside the Docker app container.

Set these variables for local transcription:

- `FASTER_WHISPER_MODEL`
- `FASTER_WHISPER_DEVICE`
- `FASTER_WHISPER_COMPUTE_TYPE`
- `FASTER_WHISPER_DOWNLOAD_ROOT`
- `FASTER_WHISPER_LOCAL_FILES_ONLY`
- `FASTER_WHISPER_LANGUAGE`
- `FASTER_WHISPER_BEAM_SIZE`
- `FASTER_WHISPER_CPU_THREADS`
- `FASTER_WHISPER_MEMORY_LIMIT`
- `FASTER_WHISPER_INITIAL_PROMPT`

The Docker Compose stack stores faster-whisper model files in the
`faster_whisper_models` volume mounted at `/models/faster-whisper`. This keeps
the model local and avoids redownloading it on every container restart.
Set `FASTER_WHISPER_LOCAL_FILES_ONLY=true` after the model exists locally if the
container should not attempt any model download.
`FASTER_WHISPER_CPU_THREADS` defaults to `8` and is passed directly to
faster-whisper's local model loader. `FASTER_WHISPER_MEMORY_LIMIT` defaults to
`8g` and controls the Docker Compose memory limit for the app container, where
local transcription runs.
`FASTER_WHISPER_INITIAL_PROMPT` is passed to faster-whisper as an initial
formatting prompt. The default prompt asks the model to render spoken
punctuation words such as `comma`, `period`, and `question mark` as punctuation
marks instead of spelling those words. Set it blank in `.env` to disable that
formatting hint.
For reliable local transcription, run the Docker stack on a server with at least
8 CPU cores and 10 GB of RAM so the app container can use its default 8-thread,
8 GB faster-whisper allocation while leaving memory for PostgreSQL, Nginx, and
the host operating system.

`TRANSCRIPTION_PROVIDER=mock` proves the transcription path without loading a
local model. `TRANSCRIPTION_PROVIDER=disabled` rejects transcription attempts.

The active-job and review-detail recorder streams `MediaRecorder` chunks to
`WebSocket /jobs/{job_id}/description/audio/stream`. The first WebSocket
message carries metadata and the CSRF token, then binary audio chunks are sent
as soon as the browser produces them. The server starts a best-effort interim
transcription from the first buffered chunk. The **Record** button uses an
orange treatment and sits beside **AI Cleanup** when cleanup is enabled on Work
in Progress and review detail. It becomes a **Stop recording** button while
browser capture is active. Stopping capture lets the browser flush the final
chunk, sends WebSocket
`finish`, returns the button to its idle label, keeps that disabled button in
the shared loading state, and shows clear text progress:
**Sending data to server...**, then **Converting audio to text...**, then
**Conversion complete.** after the final saved transcript is returned. Status
lines do not show spinners; the active button shows the spinner. A bounded error
response is shown instead if the stream or provider fails. Review recording is
available only before the job has been submitted to Autotask.

Raw audio is not stored by default. The app keeps the streamed recording in
memory only, sends buffered bytes to the local provider through a temporary
file, deletes that temporary file, and stores only the returned text and safe
status. The existing `MAX_AUDIO_UPLOAD_BYTES` setting also limits streamed
recordings.

### AI Summary Cleanup

AI summary cleanup is separate from speech-to-text. It sends the current
editable summary text to the configured AI provider through the Job Logger
server, then replaces the summary textarea with the cleaned text returned by
that provider.

The feature is disabled by default. Configure it in Docker or `.env`:

- `AI_CLEANUP_ENABLED=true`
- `AI_CLEANUP_PROVIDER=gemini`, `grok`, `ollama`, or `lm_studio`
- `AI_CLEANUP_TIMEOUT_SECONDS`, default `20`
- `AI_CLEANUP_MAX_INPUT_CHARS`, default `12000`
- `AI_CLEANUP_INSTRUCTIONS`

Job Logger sends `AI_CLEANUP_INSTRUCTIONS` through the provider's instruction
channel, such as the system message or local-provider system field. The visible
summary prompt contains the cleanup task, minimal job context, and the summary
text without duplicating those configured instructions.

For Gemini free-tier cleanup, configure:

- `GEMINI_API_KEY`
- `GEMINI_CLEANUP_MODEL`, default `gemini-3.5-flash`
- `GEMINI_CLEANUP_API_BASE_URL`, default `https://generativelanguage.googleapis.com/v1beta`

For GroqCloud free/start-plan cleanup, configure:

- `GROQ_API_KEY`
- `GROQ_CLEANUP_MODEL`, default `llama-3.1-8b-instant`
- `GROQ_CLEANUP_API_BASE_URL`, default `https://api.groq.com/openai/v1`

The provider value `grok` uses GroqCloud. `GROK_API_KEY`,
`GROK_CLEANUP_MODEL`, and `GROK_CLEANUP_API_BASE_URL` are accepted as
compatibility fallbacks, but the `GROQ_*` names match Groq's official docs.

For Ollama cleanup on loopback or a private LAN, configure:

- `OLLAMA_CLEANUP_MODEL`, default `llama3.1`
- `OLLAMA_CLEANUP_API_BASE_URL`, default `http://127.0.0.1:11434/api` for
  non-Docker runs

For Docker Compose, `.env.example` and `docker-compose.yml` default the Ollama
URL to `http://host.docker.internal:11434/api` so the app container can reach
an Ollama process running on the same host. The selected model must already be
available to that Ollama server. To use an Ollama server elsewhere on the
private network, set the base URL to that server's private IP and API path, for
example `OLLAMA_CLEANUP_API_BASE_URL=http://172.25.1.99:11234/api`. Job Logger
appends `/generate` to that base URL. If Job Logger is running in Docker, the
Ollama server must listen on an interface reachable from the app container; keep
firewall rules tight and do not expose the model server publicly.

For LM Studio cleanup on loopback or a private LAN, configure:

- `LM_STUDIO_CLEANUP_MODEL`, default `local-model`
- `LM_STUDIO_CLEANUP_API_BASE_URL`, default `http://127.0.0.1:1234/v1` for
  non-Docker runs
- `LM_STUDIO_API_KEY`, optional, only if the local LM Studio server requires it

For Docker Compose, `.env.example` and `docker-compose.yml` default the LM
Studio URL to `http://host.docker.internal:1234/v1`. Set
`LM_STUDIO_CLEANUP_MODEL` to the model identifier shown by LM Studio for the
loaded model. To use an LM Studio server elsewhere on the private network, set
the base URL to that server's private IP and OpenAI-compatible `/v1` path, for
example `LM_STUDIO_CLEANUP_API_BASE_URL=http://172.25.1.99:11234/v1`. Job
Logger appends `/chat/completions` to that base URL. If Job Logger is running
in Docker, the LM Studio server must be reachable from the app container; keep
firewall rules tight and do not expose the model server publicly.

Ollama and LM Studio cleanup URLs are intentionally restricted to loopback,
Docker host aliases, or private-network IP ranges such as `10.x.x.x`,
`172.16-31.x.x`, and `192.168.x.x`. Public URLs and arbitrary public hostnames
are rejected.

When enabled, active mobile jobs and review detail show **AI Cleanup** with the
summary box. On active mobile jobs, **Record** and **AI Cleanup** share one row;
on unsubmitted review detail, recording and cleanup remain available with the
review layout. Cleaned text replaces the textarea and mobile saves it through
the existing active-summary save endpoint. Cleanup progress, success, and
failure details use the same plain-text status line as audio recording; the
**AI Cleanup** button itself shows the shared spinner while cleanup is in
progress, and cleanup waits until audio recording/transcription is finished. On
review detail, the cleaned text replaces the textarea; non-submitted jobs
autosave as usual, while submitted jobs still require **Edit Entry** to patch
the existing Autotask time entry.

AI cleanup requests require the local authenticated session and CSRF token. The
server sends bounded summary text plus minimal job context to the selected
provider, sets `store=false` for Gemini requests, and records only metadata such
as provider, model, source, and text lengths in the audit log. Do not put
Gemini or Groq keys, private-network provider API keys, private cleanup
instructions, or customer summary text in source control.

Provider setup and data-handling docs:

- Gemini text generation: https://ai.google.dev/gemini-api/docs/text-generation
- Gemini free-tier pricing and data terms: https://ai.google.dev/gemini-api/docs/pricing
  and https://ai.google.dev/gemini-api/terms
- Groq quickstart and data controls: https://console.groq.com/docs/quickstart
  and https://console.groq.com/docs/your-data
- Ollama API introduction and generate endpoint: https://docs.ollama.com/api/introduction
  and https://docs.ollama.com/api/generate
- LM Studio local server and OpenAI-compatible endpoints:
  https://lmstudio.ai/docs/developer/core/server and
  https://lmstudio.ai/docs/developer/openai-compat

### Autotask

Autotask is mandatory for normal production use because the app now uses
Autotask Companies and Tickets to decide which ticket receives time. Production
must run with `AUTOTASK_PROVIDER=autotask`. The `mock` provider is only for
tests or isolated development.

`AUTOTASK_PROVIDER=autotask` enables live REST API calls. Set:

- `AUTOTASK_BASE_URL`
- `AUTOTASK_USERNAME`
- `AUTOTASK_SECRET`
- `AUTOTASK_API_INTEGRATION_CODE`

Do not set a global `AUTOTASK_RESOURCE_ID`. Each managed web user has a required
Autotask resource ID on `/users`; Job Logger uses that user-specific resource ID
for service-call lookup and for `TimeEntries.resourceID` when that user
submits work. Job Logger does not send Autotask's optional
`ImpersonationResourceId` header, so Docker and `.env` files must not define a
global impersonation resource.

Do not set static role or billing-code IDs. When a reviewed job is submitted,
Job Logger re-queries the selected ticket and uses that ticket's
`assignedResourceroleID` for `TimeEntries.roleID` when available. If the ticket
does not return an assigned role, Job Logger first checks whether the submitting
web user is a secondary resource on that ticket and uses that ticket-specific
`TicketSecondaryResources.roleID`. If no matching secondary resource role
exists, it uses the ticket's `assignedResourceID` to resolve that resource's
default or single active `ResourceServiceDeskRoles.roleID`, then uses the
submitting web user's configured default service-desk role when one has been
selected on `/users`, then falls back to the submitting web user's default or
single active service-desk role. The time entry still uses the submitting
managed user's Autotask resource ID as `TimeEntries.resourceID`. Billing code /
Work Type is also ticket-driven: Job Logger omits
`TimeEntries.billingCodeID` so Autotask inherits the selected ticket's
`billingCodeID` on create without requiring separate Allocation Code edit
permission.

The super-admin `/users` page can query Autotask Resources through the server
while adding or editing a web user. Resource names are displayed in Autotask's
`Last, First` format in a dropdown-style picker, and choosing one fills the
required resource ID field. If Autotask returns an email address for the chosen
resource, the email is saved with the managed web-user account and displayed in
the Users table for future user-scoped features. The form can also load active
`ResourceServiceDeskRoles` for the selected resource and save one optional
default service-desk role. That configured role is used only as a time-entry
fallback after ticket-assigned role sources fail. Each table row also has a
refresh icon that re-runs the server-side resource lookup and updates stored
name/email metadata only after the returned resource ID matches the user's saved
resource ID. The browser never receives Autotask credentials and cannot query
Autotask directly.

Autotask ticket status writes are optional. By default, Job Logger creates and
updates `TimeEntries` without patching `Tickets.status`, which works for API
users that have time-entry permissions but cannot change ticket workflow
status. Set `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=true` only when the API user
is allowed to patch `Tickets.status` and you want Job Logger to advance or close
tickets automatically.

Autotask ticket status picklist IDs vary by tenant. Configure these only when
ticket status updates are enabled:

- `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED`
- `AUTOTASK_STATUS_IN_PROGRESS_ID`
- `AUTOTASK_STATUS_WAITING_CUSTOMER_ID`
- `AUTOTASK_STATUS_WAITING_PARTS_ID`
- `AUTOTASK_STATUS_FOLLOW_UP_ID`
- `AUTOTASK_STATUS_COMPLETE_ID`

Open-ticket and service-call selection do not use the Autotask `Tickets`
endpoint for status changes; they only default the local editable ticket status
to `In progress`. With ticket status updates disabled, the selected status stays
local and does not block `TimeEntries` creation. With ticket status updates
enabled, Autotask ticket status writes wait until the complete time entry is
submitted or an already submitted entry is explicitly edited.

Managed web users can enable **Submit from Work in Progress** on `/config`.
This option is off by default so existing accounts keep the review-first
workflow. When enabled, the active Work in Progress finish button changes to
**Submit to Autotask** and uses the same idempotent Autotask submission service
as Review acceptance. Direct submission still requires the selected ticket
number, ticket status, rounded end time, client, and summary notes. If those
local fields are missing, the job stays active so the technician can correct
it. If Autotask itself rejects the submission, the job moves to the failed
submission review state with the safe error message and can be retried from
Review.

The mobile page can search Autotask companies while entering the client name.
Selecting a company stores the display name and Autotask company ID with the job
so open-ticket lookup can target the exact selected company instead of relying
only on a typed name. During active work, that selected Autotask client is shown
as read-only for the job so the client name cannot drift away from the company
ID used for ticket lookup. Client names can still be typed manually before an
Autotask company is selected. Ticket numbers are populated from open-ticket
selection instead of manual entry.

Autotask company search results and selected-company metadata are cached
in-process for two hours because company names rarely change. Empty company
search results are not treated as authoritative cache hits, so a company missing
from cache can still be queried from Autotask. Ticket status picklist labels and
other Autotask lookup data remain on a 15-minute cache. Recently displayed
open-ticket selection lists are cached server-side for two minutes so selecting
a ticket that was just shown does not re-query Autotask on the critical tap
path. The initial `/home` page and blank Start Work route do not run an
Autotask contactability check. Live company and ticket queries request
`MaxRecords=500` and follow Autotask
pagination links so larger tenants are not limited to the first page of results.
Pagination is bounded and fails safely instead of silently showing partial
customer or ticket lists. For POST query pagination, Job Logger follows
`nextPageUrl` with POST and the original query body because Autotask rejects GET
follow-up calls for those resources.

The mobile and review pages can query open Autotask tickets from the selected
job's stored company ID or stored client name. If no tickets have been loaded,
the whole Open tickets panel is clickable and keyboard-activatable. On mobile,
that panel saves the current active-job client fields before loading open
tickets. Saved clients do not auto-load tickets when the Work in Progress card
renders; click the panel to load them. Both mobile and review ticket lookup show
the spinner loading state while Autotask data is being fetched or a selected
ticket is being saved. Open-ticket choices show the ticket number, title,
ticket status, company name, and detected `Remote`, `On-Site`, or `Not
specified` work-location label from the ticket title and description.
Remote/On-Site choices use the same color treatment as service-call cards on
both Work in Progress and Review.
Selecting a returned ticket fills the mobile job's hidden ticket number, stores
the selected ticket title for the review detail heading, stores the bounded
ticket description for read-only context, and automatically saves the active-job
changes or review ticket selection. The mobile Work in Progress card shows the
selected ticket number, ticket name, ticket status, and ticket description
after selection. Selection does not update Autotask ticket status. It stores
verified local ticket metadata and defaults the editable local ticket status to
`In progress`; the first Autotask write waits until the full time entry is
submitted or an already submitted entry is explicitly edited/deleted.
Long ticket descriptions stay inside a scrollable read-only box instead of
expanding the mobile page indefinitely; phone-sized layouts cap that visible
box at about 12 lines, and wider layouts cap it at about 25 lines. On the
review page, the stored ticket number, ticket description, and client name are
read-only identity/context fields; review save and submit use the stored values
instead of trusting form posts. Once a job has a ticket number, the open-ticket
picker is hidden for that job.

When an active job slot is available, the mobile start panel also lists Autotask
service calls assigned to the logged-in web user's Autotask resource ID for the
selected local date. The mobile page renders first with a loading state and no
synchronous Autotask calls. After the window load event, the browser fetches
`/home/service-calls` so slow Autotask service-call lookups show progress
instead of delaying the whole start screen. The compact date navigator can move
to the previous or next day, and tapping the displayed day opens a calendar
picker. Current-week days are labeled by day name with today/yesterday/tomorrow
context when applicable; dates outside the current week use a calendar date.
Each service-call choice shows the client name, the detected `Remote` or
`On-Site` value from the service-call details text, the local start/end time
range such as `4:00pm-5:00pm`, and the associated ticket title. Remote and
On-Site cards use stronger distinct accent colors and badges so scheduled call
type is easy to scan without wasting mobile screen space.
Tapping a service call starts an active job with the server-verified ticket
number, ticket title, bounded ticket description, client name, company ID, and
detected work-location mode. It defaults the local editable ticket status to
`In progress` without updating Autotask. The browser submits only the
service-call ticket association ID, selected date, and CSRF token; the server
re-checks that date's resource-specific service-call list before creating the
job. If service-call lookup fails because permissions are missing, the blank
Start Work path remains
available.

Service-call lookup requires the Autotask API user to read `ServiceCalls`,
`ServiceCallTickets`, and `ServiceCallTicketResources`, in addition to the
Companies and Tickets permissions already required by the app.

The shared page data is styled through `app.css`, then viewport-specific
`phone.css` or `desktop.css` loads automatically with media queries so phones
and desktop browsers get appropriately sized layouts. In a full browser view,
the `/home` Home screen lays out Start Work beside the service-call list, and
Work in Progress puts job details beside notes and finish actions for easier
scanning. Phone-sized authenticated
layouts hide the brand mark and desktop logout button, place left navigation
icons on the left, center the version link, and put right-side actions on the
right. Managed web users see Home and Review on the left, with Config and a
logout icon on the right. The config super admin sees Users, Review, and
Diagnostics on the left, with a logout icon on the right. The mobile logout
icon submits the normal CSRF-protected `/logout` form. Full-width `/home`,
review, debug, and other non-mobile pages keep the explicit desktop logout
button. Mobile submit actions show a loading overlay once the
tap is accepted so slow redirects or Autotask lookups do not look like ignored
buttons; rounded start/stop `-15` and `+15` adjustments skip the full-page
overlay so those small time changes feel immediate.
In active mobile Work in Progress cards, **End Work** or **Submit to Autotask**
shares a row with the destructive **Delete** action to keep the active-card
controls compact. Active jobs selected on Review detail also show **End Work**
beside **Delete time entry**, and the button returns to that review detail after
the job is ended.
The app also queries `Tickets` by `ticketNumber`, creates a `TimeEntries` row,
and records every attempt in `submission_attempts`.

After a job is successfully submitted to Autotask, ticket and client identity
stay read-only. The selected review detail allows job date, start time, end
time, summary notes, and ticket status edits through **Edit Entry**, which
patches the existing `TimeEntries` row instead of creating a duplicate entry.
With `AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=true`, **Edit Entry** can also
patch `Tickets.status` for intentional status changes, including temporarily
moving a previously `Complete` ticket to `In progress` before the time-entry
patch. With the default disabled setting, **Edit Entry** patches only
`TimeEntries`.
The same submitted detail also has **Delete From Autotask**, which deletes the
existing Autotask time entry and returns the local job to review without
removing the local job record. If Autotask refuses the delete, the job remains
submitted and the safe failure message is shown in review.
Save, accept/resend, retry, ticket selection, and local **Delete time entry**
cleanup remain blocked for submitted jobs. **Delete time entry** may remove
active or other unsubmitted local jobs from the selected review detail when the
logged-in managed web user owns the job.

The selected job's audit timeline is collapsed by default and can be expanded
from the review detail when troubleshooting or checking history.

The mobile Work in Progress card stores a work-location mode of `Remote` or
`On-Site`, defaulting to `Remote`. This mode does not appear in the mobile
summary text. Review detail shows the complete Autotask-bound summary, such as
`Remote replaced firewall` or `On-Site replaced firewall`, so the prefix can be
corrected before submission or **Edit Entry**. The server parses that prefix
back into the stored work-location mode and keeps local note storage unprefixed.

Ticket `TimeEntries` payloads use the selected ticket's
`assignedResourceroleID` for `roleID` when available. If Autotask returns the
ticket without that assigned role, Job Logger first checks
`TicketSecondaryResources` for the submitting web user's ticket-specific role,
then uses `Tickets.assignedResourceID` to resolve that resource's default or
single active service-desk role, then uses the submitting web user's configured
default service-desk role from `/users` when present, then falls back to the
submitting web user's default or single active `ResourceServiceDeskRoles.roleID`.
Payloads
intentionally omit `billingCodeID` /
Allocation Code values; Autotask inherits the selected ticket's Work Type on
create, which avoids requiring the API resource to have Allocation Code edit
permission for ticket time entries. Existing `AUTOTASK_ROLE_ID` and
`AUTOTASK_BILLING_CODE_ID` values in older `.env` files are ignored by the app.

Do not configure a global Autotask impersonation resource. Job Logger uses the
logged-in or owning managed web user's saved Autotask resource ID in
user-scoped payloads and service-call filters, but live calls do not send the
optional Autotask `ImpersonationResourceId` header. Super-admin Resource setup
and debug connectivity checks run without a managed-user context.

The `/debug` page is available only to the config super admin. Managed web
users do not see the Debug menu item, and direct `/debug/*` requests from those
sessions return 403. It shows the source-controlled application version and
includes **Test Autotask API** and **Log out web users** buttons. The logout
button forces all managed web users to sign in again while leaving the config
super admin signed in. All authenticated pages also include a discreet version
link to `/changelog`. The debug Autotask check verifies required workflow
configuration and the live Companies/Tickets API calls used by the app. The
debug button is manual and always runs a fresh live check. It is not used by the
initial mobile page or blank Start Work route.

The same `/debug` page also shows compact, paginated successful-login and
failed-login windows. Failed local app login attempts are appended as JSON Lines
to `/data/logs/job-logger-login-failures.log`, and successful attempts are
appended to `/data/logs/job-logger-login-successes.log` inside the app
container. Docker Compose bind-mounts that directory from
`${HOST_LOG_DIR:-/var/log/job-logger}`, so the default host-readable files are
under `/var/log/job-logger/`. The logs and debug page include timestamp, client
IP, proxy header details, username, user agent, request path, host/proxy
metadata, account kind, authentication method, failure reason, and
password-present/length metadata for failures. When `X-Forwarded-For` is
present, the first forwarded address is shown as the client IP so Cloudflare
Tunnel deployments show the actual browser address instead of the tunnel peer.
Successful-login rows use a yellow account chip for the config super admin and
a green chip for managed web users.
The raw submitted password is never stored or displayed. The `/debug/logs/login-failures` and
`/debug/logs/login-successes` endpoints download the raw JSONL files for
authenticated diagnostics.

The `/debug` page also includes a **Disk space** card for the app-visible root
filesystem, `LOG_DIR`, and `AUTOMATIC_BACKUP_DIR`. The card warns at 85% used
or under 5 GB free, and becomes critical at 95% used or under 1 GB free. In
Docker this reflects storage visible from the app container, including the
mounted log and backup paths; monitor the PostgreSQL volume separately unless
that volume is also exposed to the app container.

At the bottom of `/debug`, the **Application Log** card shows the newest 200
lines first from `${LOG_DIR}/app.log`, normally
`/var/log/job-logger/app.log` on the Docker host. The card's viewport shows
about 20 lines at a time and scrolls for the rest; use the host log files for
longer history.

The app also creates automatic full-database backups every hour when
`AUTOMATIC_BACKUPS_ENABLED=true`, which is the default. Docker Compose stores
them in `${AUTOMATIC_BACKUP_DIR:-/data/logs/backups}`, backed by the same
host-mounted `${HOST_LOG_DIR:-/var/log/job-logger}` runtime directory. Retention
keeps the newest 6 hourly backups plus one daily backup for today and one for
each of the prior 2 days; expired automatic backups are purged after each
successful automatic backup.

The `/debug` page also includes **Automatic database backups**, **Download Full
Backup**, and **Restore Full Backup** controls. Backups are sensitive `.json.gz`
files containing all Job Logger database tables, including managed web-user
password hashes and email metadata, jobs, submission attempts, and audit events.
Store backup files somewhere private because they contain account, customer,
ticket, and work-summary history.

To restore, upload a Job Logger full-backup file on `/debug` and type
`RESTORE`. Restore validates the archive format, required tables, and columns
before deleting current app rows. A successful restore replaces the current app
database contents with the backup contents, then records a new restore audit
event. Backups from v1.0.2 that predate the **Submit from Work in Progress**
preference restore with that new option defaulted off. Backups that predate the
managed-user session invalidation column restore with no users forced out by
that missing column. The default restore upload cap is 250 MB:
`MAX_BACKUP_RESTORE_BYTES` controls app-side validation and
`NGINX_RESTORE_MAX_BODY_SIZE` controls the matching nginx body limit for
`/debug/restore`.

To restore an automatic backup, use the per-backup restore row on `/debug` and
type `RESTORE` beside the selected file. The same validation, replacement, and
post-restore audit behavior used by uploaded full-backup restores applies.

The Docker Compose database uses the named `postgres_data` volume mounted at
`/var/lib/postgresql/data` inside the PostgreSQL container. That volume persists
across normal container rebuilds and recreates. Do not run `docker compose down
-v`, prune volumes, or change the Compose project/stack name unless you have a
verified backup and intend to replace or discard the existing data.

The `scripts/discover_autotask_ids.py` helper also prints a workflow endpoint
preflight section. Ticket-status ID discovery can succeed even when the
Autotask API user cannot query Companies or Tickets, so use the preflight
result and the `/debug` failed-operation label when diagnosing Autotask HTTP
500 or permission failures. Some Autotask permission denials are returned as
HTTP 500 responses, so check the preflight detail before changing credentials.

When Autotask rejects `TimeEntries` creation/update, Job Logger surfaces bounded
body-level error details when Autotask provides them. This usually identifies
the specific missing permission, invalid role, billing code, resource, or
required field more clearly than a generic HTTP 500 message. If the error names
ticket status updates or `Tickets.status`, leave
`AUTOTASK_TICKET_STATUS_UPDATES_ENABLED=false` unless the API user has the
ticket workflow permissions needed to change statuses.

## Time Handling

All user-facing dates and times use `America/Detroit`.

User-facing times display in 12-hour `am`/`pm` format. Review forms also accept
legacy 24-hour submissions so stale browser pages do not fail during deployment.

All database timestamps are stored in UTC.

Review uses one local job date with a start time and end time. Jobs are not
allowed to span multiple dates; edits where the end time is not after the start
time on the selected date are rejected.

Start time, end time, and resulting duration are rounded to 15-minute intervals.
The active mobile end-work path still protects against a zero-minute rounded
duration. Review detail shows the active Work in Progress rounded stop preview
when an active job is selected, but review save ignores that displayed end time
until the user actually ends the job. Ended review edits must explicitly choose
a valid later end time on the same job date.

## Ticket Numbers

The mobile page starts jobs without ticket or client fields. After work starts,
select the client on the active job card, then choose an open Autotask ticket
from the returned list. The ticket number is not manually editable on mobile;
the open-ticket selection fills and saves it automatically.

Open in-progress jobs also have a **Delete** action on the mobile work card.
That action discards only the active job before it reaches review history and
records an audit event. Reviewed jobs still use the review workflow actions.

Ticket numbers must use the Autotask format `TYYYYMMDD.####`, for example
`T20260326.0018`.

## Testing

Run local checks with:

```bash
python -m compileall job_logger tests
pytest
ruff check .
docker compose config
```
