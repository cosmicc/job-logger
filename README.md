# Job Logger

Job Logger is a security-focused Dockerized Python web application for quickly
recording Autotask time entries or customer-visible ticket notes from a phone
or web browser, reviewing or directly submitting recorded jobs, and sending
accepted records to Autotask.

End users can use [USER_MANUAL.md](USER_MANUAL.md) for a full walkthrough of
sign-in, password reset, Work in Progress, Review, Config, and common app
messages.

## Architecture

- FastAPI serves the application.
- Nginx fronts the FastAPI web interface inside Docker.
- Jinja templates render the mobile capture page, desktop review page, user
  manager, config page, and diagnostics.
- PostgreSQL stores managed web users, jobs, review fields, submission attempts,
  per-user preferences, sanitized login attempts, and audit events.
- Alembic manages database migrations.
- Cloudflare Tunnel publishes the app without opening an inbound firewall port.
- Cloudflare Access can protect the public hostname before the app login page.
- Optional self-service password reset uses SMTP mail and can use Cloudflare
  Turnstile human verification.
- Configurable providers support mock or live speech-to-text and Autotask modes.

Cloudflare documents Tunnel as an outbound `cloudflared` connector and Access as
the control point for self-hosted applications:

- https://developers.cloudflare.com/tunnel/setup/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/

Autotask REST API references used by this app:

- TimeEntries entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TimeEntriesEntity.htm
- TicketNotes entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketNotesEntity.htm
- Tickets entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketsEntity.htm
- Companies entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/CompaniesEntity.htm
- Resources entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ResourcesEntity.htm
- ResourceServiceDeskRoles entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ResourceServiceDeskRolesEntity.htm
- Roles entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/RolesEntity.htm
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

3. Replace `APP_SECRET_KEY` and `POSTGRES_PASSWORD` with long random values.
   Docker Compose fails closed if these secrets are missing, and production
   startup rejects the documented `replace-with-*` placeholders.

4. Set `LOG_LEVEL` to `DEBUG`, `INFO`, `WARNING`, or `ERROR` to control stdout
   and stderr log verbosity. Docker defaults to `INFO`; use `docker compose
   logs app` or the runtime log collector for history.
   Set `DEV_BUILD=true` only for dev deployments that should show the
   authenticated Help button in yellow, show `DEV` on the Help page, and
   suppress Pushover health notifications.

5. Start the stack:

   ```bash
   docker compose up -d --build
   ```

   `.env.example` enables `COMPOSE_PROFILES=local-db,bundled-edge`, so this
   starts the bundled PostgreSQL, nginx, and `cloudflared` containers. For a
   remote PostgreSQL server, remove `local-db` and provide `DATABASE_URL`. For
   an external nginx and `cloudflared` deployment, remove `bundled-edge`.

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
   ID. The users page shows managed accounts in a table with per-row edit and
   enable/disable controls as compact icons, including any email address
   captured from Autotask Resource lookup, last successful login time, and a
   green or red Device sign-in key icon showing whether the account has any
   registered passkeys. The table also shows whether a managed user has Admin
   access to Diagnostics, but it does not display internal Autotask resource ID
   or role ID values. Row actions can send a password reset email, resend the
   welcome email, edit, enable/disable, or delete an account. Delete fully
   removes users that have no jobs. Users with linked jobs are hidden, signed
   out, and restored with their job history when a new user is added with the
   same Autotask resource ID. The
   add-user form suggests a username from the name, such as `jblow` for
   `Joe Blow`, and add/edit forms can search Autotask Resources so you can
   select the matching `Last, First` resource and fill its ID. The same form can
   load active service-desk roles for that resource, show role names when
   Autotask role metadata is readable, and save the selected numeric role ID as
   an optional default fallback for tickets that do not return usable role data.
   Add/edit forms also include a default-off Admin checkbox that grants that
   managed user full `/debug` Diagnostics access only.
   When Autotask returns an email for the selected resource, Job Logger saves it
   with that web-user account. Managed-user passwords must be at least 8
   characters and include lowercase, uppercase, number, and symbol characters.
   Passwords created or reset by the config super admin are temporary; the
   managed user must choose a new password on the next sign-in before using the
   rest of the app.
   The first web user you create takes ownership of any existing unowned jobs
   from earlier single-user installs.

8. Managed web users can open `/config` to choose their visual theme and how
   finished Work in Progress entries are submitted. Dark is the default, and changes save and apply
   immediately without a Save button. Light and dark themes apply to mobile and
   web pages for that login only. The **Submit from Work in Progress** workflow
   option is not a workflow availability toggle. It is off by default; when
   enabled, ending work submits the completed time entry or ticket note to
   Autotask immediately instead of requiring Review first. The same page
   includes an explicit **Change password** action with two matching password
   fields and the password requirements shown in the password card; password
   changes are not autosaved. When a temporary password is required, Config
   shows only the password-change step until the password is changed. Managed
   users can also add passkeys after signing in normally once. The config
   super-admin account has no user settings and always uses dark mode.

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
  Cloudflare tunnel token, public hostname, and WebAuthn origin.
- Use a separate Cloudflare Tunnel and public hostname for dev testing.
- Use a separate Docker Compose project name, PostgreSQL volume or remote
  database, and backup directory so dev cannot overwrite production data.
- Use a different `HTTP_PORT`, such as `11031`, if production and dev
  run on the same Docker host.
- Set `DEV_BUILD=true` in the dev `.env` so the authenticated header clearly
  marks the instance as dev and Pushover health notifications stay disabled
  even if `PUSHOVER_ENABLED=true` is present in the shared environment.
- Set `APP_ENV=development` only for an isolated dev instance. Production keeps
  `APP_ENV=production`. Keep `CLOUDFLARE_ACCESS_REQUIRED=true` for
  internet-facing deployments once the matching Cloudflare Access application
  is configured.
- Use real Autotask credentials only when the dev workflow intentionally needs
  live Autotask testing. Keep `AUTOTASK_PROVIDER=mock` for isolated UI or
  workflow-only checks.

Example same-host dev startup:

```bash
COMPOSE_PROJECT_NAME=job_logger_dev \
HTTP_PORT=11031 \
DEV_BUILD=true \
docker compose up -d --build
```

Do not merge `dev` into `main` until the dev instance has passed the intended
validation and a production release is ready.

## Cloudflare Tunnel

The Compose sample starts Nginx and `cloudflared` by default through the
`bundled-edge` profile. This keeps the single-host production path simple: the
app, Nginx reverse proxy, tunnel connector, and optional local PostgreSQL
container can come up with one `docker compose up -d --build` command. Remove
`bundled-edge` from `COMPOSE_PROFILES` when an external nginx and
`cloudflared` deployment handles the public edge.

1. Create a Cloudflare Tunnel in the Zero Trust dashboard.
2. Add a public hostname that routes to this Docker service URL:

   ```text
   http://127.0.0.1:11030
   ```

   The Compose-managed `cloudflared` service uses host networking, so
   `127.0.0.1` is the stable address from the connector to the localhost
   Nginx port.

3. Create a Cloudflare Access self-hosted application for that hostname.
4. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN` when using the
   bundled `cloudflared` service.
   If this token is missing or invalid, Cloudflare will return a 502 and
   `cloudflared` will repeatedly restart.
5. Prefer `CLOUDFLARE_ACCESS_REQUIRED=true` for production when the matching
   Cloudflare Access application is configured. Docker Compose defaults this
   setting to true, but `APP_ENV=production` no longer refuses startup solely
   because the optional Access header gate is disabled. Secure session cookies
   are still required in production.
6. Set `APP_PUBLIC_BASE_URL` to the same public HTTPS origin before enabling
   account emails, because password reset and welcome emails use that value for
   absolute links. Keep `/forgot-password` and `/reset-password/...` behind the
   same Cloudflare Access application as the login page.
7. Set `WEBAUTHN_ORIGIN` to the public HTTPS origin that phones see in the
   browser, such as `https://logger.example.com`, before using passkeys through
   Cloudflare Tunnel. Use this setting whenever the app needs the
   browser-facing public URL. The bundled nginx origin also preserves
   Cloudflare's forwarded HTTPS scheme for WebAuthn, but this explicit setting
   is the safest production pin. Set `WEBAUTHN_RP_ID` to the same hostname if
   the app cannot reliably derive the public host from forwarded headers.
8. Start the full stack:

   ```bash
   docker compose up -d --build
   ```

   After changing `HTTP_PORT` or the nginx proxy config, recreate the
   app-facing services so Docker applies the new container environment and
   rendered nginx config:

   ```bash
   docker compose up -d --build --force-recreate app nginx cloudflared
   ```

Nginx is the web front end for this deployment. Public mobile and review
traffic should enter through the Cloudflare Tunnel hostname, reach the host-exposed
Nginx endpoint on `127.0.0.1:11030` from the Compose-managed connector by
default, and then proxy to FastAPI at `http://app:8000`.

The app container is exposed only to the private Compose network. The local
troubleshooting URL reaches Nginx on `127.0.0.1`, not the app container
directly.

Nginx always binds `HTTP_PORT` on `127.0.0.1` so the Compose-managed tunnel can
reach the origin through host networking without exposing the port on the LAN.
If `HTTP_PORT=2082`, set the Cloudflare Tunnel service route to
`http://127.0.0.1:2082`.

`HTTP_PORT` is the configurable localhost-facing port.
All other service ports are fixed internally and are not intended to be changed
via environment:

- Nginx listens on container port `80`.
- App listens on container port `8000`.
- PostgreSQL stays internal to Compose on container port `5432`.

### Compose Deployment Modes

The default `.env.example` uses `COMPOSE_PROFILES=local-db,bundled-edge`, which
starts the bundled PostgreSQL, nginx, and `cloudflared` services.

Use these profile combinations for standalone Compose:

- `COMPOSE_PROFILES=local-db,bundled-edge`: bundled PostgreSQL and bundled
  nginx/cloudflared.
- `COMPOSE_PROFILES=bundled-edge`: remote PostgreSQL with bundled
  nginx/cloudflared.
- `COMPOSE_PROFILES=local-db`: bundled PostgreSQL with external
  nginx/cloudflared.
- `COMPOSE_PROFILES=`: remote PostgreSQL with external nginx/cloudflared.

When deploying from Portainer, keep the stack environment field or uploaded
environment file to plain `KEY=value` lines only. Do not paste markdown
headings, bullet text, or explanatory comments into Portainer's environment
editor, and do not upload `.env.example` directly without stripping comment
lines first. If redeploy fails before pulling images with an error like
`failed to read /data/compose/1/stack.env: line 1: key cannot contain a space`,
line 1 of the generated Portainer `stack.env` contains text that is not a valid
environment variable name. Remove that prose or convert it to a valid key such
as `AI_HELP_INSTRUCTIONS=Answer Job Logger support questions for end users.`
on one line.

For a remote PostgreSQL server, provide:

```env
DATABASE_URL=postgresql+psycopg://job_logger:<password>@postgres.example.com:5432/job_logger
```

If a managed PostgreSQL provider supplies a `postgresql://` or `postgres://`
URL, Job Logger normalizes it to the installed psycopg 3 driver before app
startup and migrations create database engines.

Keep the remote database private to trusted networks or TLS-protected
connections. The app uses pooled connections with `pool_pre_ping`, bounded
timeouts, and configurable `DATABASE_POOL_*` settings so remote connections are
reused without growing unbounded.

If the database is temporarily unavailable, the web container still starts and
DB-backed pages show an app-styled **Service Temporarily Unavailable** page
with automatic retry to the login page. The page intentionally does not expose
database, network, or code details.

### Docker Swarm Deployment

Use `docker-swarm.yml` for Swarm. It is image-based, does not build locally,
and expects PostgreSQL to run outside the stack:

```bash
export JOB_LOGGER_APP_IMAGE=registry.example.com/job-logger-app:1.3.0
export JOB_LOGGER_NGINX_IMAGE=registry.example.com/job-logger-nginx:1.3.0
export JOB_LOGGER_BUNDLED_EDGE_REPLICAS=1
export JOB_LOGGER_SWARM_STORAGE_PATH=/mnt/swarm-storage/job-logger
export DATABASE_URL=postgresql+psycopg://job_logger:<password>@postgres.example.com:5432/job_logger
export CLOUDFLARE_TUNNEL_TOKEN=<token>
docker stack deploy -c docker-swarm.yml job_logger
```

Build and push the app image from the root `Dockerfile` and the Nginx image
from `docker/nginx/Dockerfile` before deploying. Configure the Cloudflare Tunnel
public hostname to use the Swarm service origin `http://nginx:80`.

Before deploying the stack, mount the shared NFS storage on every Swarm node at
`${JOB_LOGGER_SWARM_STORAGE_PATH:-/mnt/swarm-storage/job-logger}` and create
these subdirectories:

```text
backups/
logs/app/
logs/nginx/
logs/cloudflared/
models/faster-whisper/
```

The app container runs as UID/GID `1000`, so `backups/`, `logs/app/`, and
`models/faster-whisper/` must be writable by that ID. The bundled nginx and
cloudflared log directories must be writable by those container runtimes.

Swarm binds that shared path into the stack so app logs, nginx logs,
cloudflared logs, automatic backups, and local faster-whisper model files
survive task rescheduling across nodes. Application data remains in the remote
PostgreSQL database selected by `DATABASE_URL`; do not add database files to
the NFS share for this stack.

For an external nginx/cloudflared Swarm edge, set
`JOB_LOGGER_BUNDLED_EDGE_REPLICAS=0` before `docker stack deploy`. This keeps
the Job Logger app service running while scaling the bundled nginx and
`cloudflared` services to zero. Attach the external nginx service to the Job
Logger overlay network created by the stack, usually `job_logger_job_logger`
when the stack name is `job_logger`, and proxy to `http://job_logger_app:8000`.
Use `docs/external-nginx-job-logger.conf` as the starting nginx config and copy
`docker/nginx/errors/` into that nginx image if you want matching app-styled
proxy error pages. Point external `cloudflared` to the external nginx service,
not directly to the app container. External nginx and cloudflared stacks should
use the same shared storage strategy for their own logs because
`docker-swarm.yml` only mounts log storage for the bundled edge services.

The standalone `docker-compose.yml` remains the path for single-host installs.

If the local troubleshooting URL is changed to a different port, update only:

```env
HTTP_PORT=<your-host-port>
```

If `cloudflared` is not running in this Compose stack, it will not be able to
resolve the Docker service name `nginx`. In that separate-deployment case,
point the tunnel at the actual host-reachable nginx URL.

Nginx is the public web edge and intentionally blocks API-style, generated
schema/documentation, and health-check paths such as `/api`, `/openapi.json`,
`/docs`, `/redoc`, `/nginx-health`, and `/health/*`. The Docker health checks
use private container networking instead of public URLs. Proxy-generated common
web errors use app-styled web service pages instead of the stock server page.
Missing app pages and other browser-facing app errors also render a Job Logger
error page with a **Back to Login** or **Back to Work** button based on the
current app session. JSON clients that request JSON keep the normal JSON error
body.

The nginx container is built from `docker/nginx/Dockerfile` with this app's
proxy template baked in. If blocked public paths do not return this app-styled
web service error page, the running container may not be using this project's
image/config and should be rebuilt.

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
on the DB health status. The app entrypoint waits briefly for real database
connectivity and runs migrations when it can. If the database remains
unavailable, the web process stays up in temporary-service mode and retries
normal startup work before serving DB-backed pages again. If the DB container
remains unhealthy, treat it as a real database startup problem. The most common
causes are a stale dev stack volume with different PostgreSQL credentials, a
damaged/incompatible data directory, or an environment mismatch in the deployed
stack.

For disposable dev stacks only, the fastest reset is to remove the failed dev
stack and its dev PostgreSQL volume, then redeploy with the intended `.env`.
Do not remove the production `postgres_data` volume unless the stored job
history is intentionally being discarded or a current backup has been verified.

### PostgreSQL Password Troubleshooting

The PostgreSQL Docker image only applies `POSTGRES_PASSWORD` when the database
volume is first initialized. If `.env` is changed later while keeping the same
`postgres_data` volume, the app can show the temporary service page while
retrying the database, or PostgreSQL can log `password authentication failed for
user "job_logger"`.

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
  to reach) is `http://127.0.0.1:11030` by default, or
  `http://127.0.0.1:<your-http-port>` when you changed `HTTP_PORT`.
- Confirm the public web path reaches the app login from the Docker host:

  ```bash
  curl -i http://127.0.0.1:11030/login
  ```

- Confirm the public health/API paths stay blocked at Nginx. These should
  return HTTP 404 with the app-styled web service error page:

  ```bash
  curl -i http://127.0.0.1:11030/health/live
  curl -i http://127.0.0.1:11030/openapi.json
  ```

- Confirm Nginx is reachable through the same origin address used by Cloudflare:

  ```bash
  curl -i http://127.0.0.1:11030/login
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
Favicon and Apple touch icon links use the same content-derived version value.
The installed-app icon comes from the web manifest and uses the icon-format Job
Logger artwork through dedicated install-icon filenames so the dark app-icon
background fills the mobile home-screen icon frame. The manifest intentionally
advertises non-maskable icons because launcher maskable cropping can over-zoom
this artwork. Mobile operating systems may update that icon after the manifest
and icon URL/content change, but some installed PWA shells keep the original
home-screen icon until the app is removed and installed again.

## Authentication And Device Sign-In

Local app sessions expire after `APP_SESSION_TIMEOUT_HOURS`, defaulting to
`12`. The value is measured in hours and is used for both the signed session
cookie lifetime and server-side login timestamp checks. After it expires, users
must sign in again.
The config super admin can also use Diagnostics to log out all managed web
users without ending the current super-admin session. Disabled managed web-user
accounts are signed out on their next request and, after the correct password is
submitted, the login screen says the account is disabled. Set
`ADMIN_CONTACT_EMAIL` to show a contact address in disabled-account messages.
The Add user page can also send a checked-by-default welcome email when the new
user has a stored email address and account email delivery is configured. The
welcome email calls the app Autotask Job Logger and includes the app link,
username, temporary-password instructions, mobile install steps, and support
contact, but not the temporary password.
The per-user password reset email action can send a reset link from the Users
page even when the public **Forgot password?** self-service flow is disabled.

The config super-admin account still signs in with `APP_USERNAME` and
`APP_PASSWORD` only. Managed web users can sign in with their username/password
or with registered device sign-in. The app labels this feature **Device
sign-in** because the underlying passkey can use a phone, browser profile,
security key, fingerprint, Face ID, PIN, pattern, or another local unlock
method. Device sign-in can be set up from `/config` after a normal password
login. On phone-sized layouts, the `/home` page prompts managed users without a
registered credential only once after each successful login, while `/config`
always keeps setup available. Job Logger stores only the public credential ID,
public key,
signature counter, and device metadata. The phone, browser, or passkey provider
keeps the private key and performs the local unlock prompt.

Device sign-in is intentionally a fallback-friendly option. If the browser does
not support passkeys, the device cancels, or signature verification fails, the
normal username/password login form remains available above the Device sign-in
button.
The login page also has a default-off **This is a public device** checkbox for
password sign-in. When selected, Job Logger signs the user out after 15 minutes
of inactivity and hides new Device sign-in setup prompts for that session. The
checkbox appears below **Forgot password?**, keeps its extra description in a
hover hint, and disables the Device sign-in button until it is unchecked.

Self-service password reset is disabled by default. When
`PASSWORD_RESET_ENABLED=true`, configure `APP_PUBLIC_BASE_URL`, mail delivery
settings, and optional Cloudflare Turnstile settings first. The same public URL
and mail delivery settings are used for optional new-user welcome emails.
Production startup fails closed if the public URL or mail dependencies are
missing for enabled password reset, and it also requires Turnstile keys when
`TURNSTILE_ENABLED=true`. Reset requests are
non-enumerating, send email only when exactly one enabled managed user has the
submitted email address, store only HMAC token hashes, expire links after 24
hours by default, invalidate old managed-user sessions after a successful
reset, and keep reset routes behind Cloudflare Access when configured.

Password reset settings:

- `PASSWORD_RESET_ENABLED`, default `false`
- `PASSWORD_RESET_TOKEN_TTL_HOURS`, default `24`
- `APP_PUBLIC_BASE_URL`, such as `https://logger.example.com`
- `MAIL_ENABLED`, `MAIL_FROM_EMAIL`, `MAIL_FROM_NAME`, and `MAIL_MODE`.
  `MAIL_MODE=smtp` uses `MAIL_SMTP_HOST`, `MAIL_SMTP_PORT`,
  `MAIL_SMTP_USERNAME`, `MAIL_SMTP_PASSWORD`, `MAIL_SMTP_STARTTLS`,
  `MAIL_SMTP_SSL`, and `MAIL_SMTP_TIMEOUT_SECONDS`. `MAIL_MODE=smtp2go` sends
  through SMTP2GO's API using `MAIL_SMTP2GO_API_KEY`.
- `TURNSTILE_ENABLED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`,
  `TURNSTILE_VERIFY_URL`, and `TURNSTILE_TIMEOUT_SECONDS`. Set
  `TURNSTILE_ENABLED=false` to run password reset without the human-verification
  widget.

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
currently `v1.3.0`. Version history starts at `v1.0.0`.

Authenticated pages show a Help button in the shared header. `/help` starts
with **Ask AI for help**, shows **Operational Status**, then shows the current
version card with a little space between each card, `Released: MM.DD.YYYY`
when that version has a release date, and a **version changelog** button that
opens concise release notes in an overlay. When monitored app health is
degraded, the top-bar alert opens the **Operational Status** card directly and
uses yellow for warning or red for critical. The Help card uses the same colors
and green when all monitored checks are operational. `/changelog` remains
available as an authenticated fallback page and uses `WEB_CHANGELOG.md` as its
source. The changelog shows version numbers without brackets, uses
`MM.DD.YYYY` dates for released versions, and lists short user-facing changes
for each version. Source entries in `WEB_CHANGELOG.md` use applicable
non-empty `Added`, `Changed`, and `Fixed` subsections like the detailed
changelog. `CHANGELOG.md` remains the detailed source changelog for operators
and agents.
`WEB_CHANGELOG.md` is only for user-facing changes; keep diagnostics,
debug-page, super-admin-only, operator-only, and agent-facing notes in
`CHANGELOG.md` only. The Help and
changelog views use the same authenticated session, dark/light theme variables,
and responsive layout system as the rest of the app.
When Docker/runtime `DEV_BUILD=true`, the authenticated Help button is yellow
on desktop and phone layouts, and `/help` shows the current version with `DEV`,
such as `v1.3.0 DEV`.

## Provider Modes

### Speech To Text

`TRANSCRIPTION_PROVIDER=faster_whisper` uses the local faster-whisper package to
transcribe job notes inside the Docker app container. Use
`TRANSCRIPTION_PROVIDER=faster_whisper_remote` to send the same browser audio
to a trusted remote faster-whisper API while keeping local transcription
available as an option.

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
Docker Swarm stores the same path under the shared
`${JOB_LOGGER_SWARM_STORAGE_PATH:-/mnt/swarm-storage/job-logger}/models/faster-whisper`
directory so rescheduled app tasks can reuse the existing model cache on any
node.
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

For remote faster-whisper, set:

- `FASTER_WHISPER_REMOTE_URL`
- `FASTER_WHISPER_REMOTE_API_KEY` when the remote service requires a bearer token.
- `FASTER_WHISPER_REMOTE_TIMEOUT_SECONDS`

Job Logger posts multipart form data to `FASTER_WHISPER_REMOTE_URL` with an
`audio` file field plus optional `model`, `language`, `beam_size`, and
`initial_prompt` fields. The remote service should return JSON with a `text`
field containing the transcript. HTTP remote URLs must stay on loopback or
private-network hosts; public remote transcription endpoints must use HTTPS.

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
- `GEMINI_API_BASE`, default `https://generativelanguage.googleapis.com/v1beta/openai/`

Gemini cleanup uses the same OpenAI-compatible `GEMINI_API_BASE` endpoint
setting as AI Help while keeping `GEMINI_CLEANUP_MODEL` and
`AI_CLEANUP_INSTRUCTIONS` separate from the Help model and support prompt.

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
autosave as usual, while submitted jobs still require **Submit changes** to
patch the existing Autotask record.
After a successful cleanup, the button changes to **Revert cleanup** and can
restore the pre-cleanup notes after page reload or navigation. Submitted Review
entries can keep a pending cleaned draft across reloads, but Autotask is still
updated only through **Submit changes**. The app stores the pre-cleanup notes
on the job only for that explicit revert workflow and clears them after revert
or successful Autotask finalization. It also clears stale revert text after
`AI_CLEANUP_REVERT_RETENTION_HOURS`, which defaults to `24`.

AI cleanup requests require the local authenticated session and CSRF token. The
server sends bounded summary text plus minimal job context to the selected
provider and records only metadata such as provider, model, source, and text
lengths in the audit log. Do not put Gemini or Groq keys, private-network
provider API keys, private cleanup instructions, or customer summary text in
source control.

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

### AI Help

The Help page is available to every signed-in user. It starts with **Ask AI for
help**, but the question-answer assistant is disabled until configured. The
page also shows operational status and the current version card with the
**version changelog** overlay button.

Set these variables to enable one-question help answers:

- `AI_HELP_ENABLED=true`
- `AI_HELP_PROVIDER=gemini`
- `GEMINI_API_KEY`, the Google AI Studio API key
- `GEMINI_MODEL`, default `gemini-3.5-flash`
- `GEMINI_API_BASE`, default `https://generativelanguage.googleapis.com/v1beta/openai/`
- `AI_HELP_MAX_TOKENS`, default `800`
- `AI_HELP_TEMPERATURE`, default `0.2`
- `AI_HELP_INSTRUCTIONS`, the server-side support prompt sent before the user's question

Job Logger calls Gemini's OpenAI-compatible chat-completions API from the
server. Set `GEMINI_API_BASE` to the OpenAI-compatible base URL above; Job
Logger appends `/chat/completions` when needed and also accepts a full
`.../chat/completions` endpoint without appending it twice. The browser never
sees the API key. Each answer is stateless: the app does not store help
questions or answers in the database. The assistant uses bounded context from
`USER_MANUAL.md`, `WEB_CHANGELOG.md`, `AGENTS.md`, agent skill files, and
selected app source to answer end-user support questions. It refuses source
code, deployment, secret, credential, and internal configuration questions.
Keep `AI_HELP_INSTRUCTIONS` focused on how the assistant should answer end-user
Job Logger support questions, and do not put secrets or private deployment
values in it.
If Gemini rejects the credentials, confirm the running container was recreated
with the current key and that the Google AI Studio key has Gemini API access.
Set `LOG_LEVEL=DEBUG` temporarily while troubleshooting AI Help. The app logs
sanitized AI Help request metadata to the console, including a trace id,
provider/model, question length, context source count, Gemini HTTP status,
provider error code when available, and timing. `/help/ask` failures that
return 400 also log a route-level error with the trace id, status code, error
class, and bounded detail. It does not log Gemini API keys, full questions,
source context, prompts, or answers.
The Help page also shows a general operational-status card. Ordinary managed
users see only whether monitored app health is operational or degraded;
Diagnostics-authorized users see the specific monitored issue details.

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

Job Logger limits concurrent live Autotask REST calls so browser lookups,
diagnostics, and submissions do not push the tenant past Autotask's thread
threshold. `AUTOTASK_MAX_CONCURRENT_REQUESTS` defaults to `2` and must be `1`,
`2`, or `3`. Keep the default unless you know no other Job Logger instance or
Autotask integration is sharing the same tenant/API user. Requests wait up to
`AUTOTASK_REQUEST_SLOT_TIMEOUT_SECONDS`, defaulting to `30`, for a slot.
PostgreSQL-backed deployments also coordinate this limiter across app processes
that share the same database.

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
`ResourceServiceDeskRoles` for the selected resource, query `Roles.name` for
human-readable labels when allowed, and save one optional default service-desk
role ID. That configured role is used only as a time-entry fallback after
ticket-assigned role sources fail. If the optional `Roles` lookup is not
permitted, the picker still works with numeric role labels. Each table row also
shows the stored email, default role ID metadata, and the last successful
managed-user login time or `Never`. The browser never receives Autotask
credentials and cannot query Autotask directly.

Autotask ticket status picklist IDs vary by tenant. Job Logger uses the selected
local app status to patch `Tickets.status` during time-entry submission and
submitted **Submit changes** resubmission, so the Autotask API user must be allowed
to update ticket workflow status. Configure all status IDs:

- `AUTOTASK_STATUS_IN_PROGRESS_ID`
- `AUTOTASK_STATUS_WAITING_CUSTOMER_ID`
- `AUTOTASK_STATUS_WAITING_PARTS_ID`
- `AUTOTASK_STATUS_FOLLOW_UP_ID`
- `AUTOTASK_STATUS_COMPLETE_ID`

Open-ticket and service-call selection do not use the Autotask `Tickets`
endpoint for status changes; they only default the local editable ticket status
to `In progress`. Autotask ticket status writes wait until the complete time
entry or ticket note is submitted, or until an already submitted record is
explicitly edited.

Managed web users can enable **Submit from Work in Progress** on `/config`.
This option is not a general workflow enable/disable setting. It only controls
whether ending a completed Work in Progress entry sends it directly to
Autotask or sends it to Review first. The option is off by default so existing
accounts keep the review-first workflow. When enabled, the active Work in
Progress finish button changes to **Submit to Autotask** for time entries or
**Submit note** for ticket notes and uses the same idempotent Autotask
submission service as Review acceptance.
Direct time-entry submission still requires the selected ticket number, ticket
status, rounded end time, verified Autotask client, and summary notes. Direct
ticket-note submission requires the selected ticket, ticket status, note title,
and note description. If those local fields are missing, the job stays active
so the technician can correct it. If Autotask itself rejects the submission,
the job moves to the failed submission review state with the safe error message
and can be retried from Review.

The mobile page can search Autotask companies while entering the client name.
Selecting a company stores the verified display name and Autotask company ID
with the job so open-ticket lookup targets the exact selected company. Typed
client text that was not selected from Autotask search results is rejected and
not saved. During active work, that selected Autotask client can still be
changed until a ticket is selected, so the technician can switch clients and
load the new client's open tickets. After ticket selection, the client is shown
as read-only for the job so the client name cannot drift away from the selected
ticket. Ticket numbers are populated from open-ticket selection instead of
manual entry. If an active job is opened from Review before any client has been
selected, Review detail shows the same authenticated Autotask
company search and saves the first verified client/company choice before ticket
lookup. Typing in that Review client search does not trigger review autosave or
summary-note warnings.

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
job's stored Autotask company ID and verified client name. If no tickets have
been loaded, the whole Open tickets panel is clickable and
keyboard-activatable. On mobile, that panel saves the current verified
active-job client selection before loading open tickets. On Review, an
empty-client active job can first save a selected
Autotask company through `/review/{job_id}/client`; after that, the normal open
ticket lookup uses the stored company selection. Saved clients do not auto-load
tickets when the Work in Progress card renders; click the panel to load them.
Both mobile and review ticket lookup show the spinner loading state while
Autotask data is being fetched or a selected ticket is being saved.
Open-ticket choices show the ticket number, title,
ticket status, company name, and detected `Remote`, `On-Site`, or `Not
specified` work-location label from the ticket title and description.
Remote/On-Site choices use the same color treatment as service-call cards on
both Work in Progress and Review.
Selecting a returned ticket fills the mobile job's hidden ticket number, stores
the selected ticket title for the review detail heading, stores the bounded
ticket description for read-only context, and automatically saves the active-job
changes or review ticket selection. The mobile Work in Progress card shows the
selected ticket number, ticket name, ticket status, and ticket description
context after selection. If Autotask returns no ticket description, Work in
Progress and Review still show the ticket description card with a clear
no-description message. Selection does not update Autotask ticket status. It
stores verified local ticket metadata and defaults the editable local ticket
status to `In progress`; the first Autotask write waits until the full time
entry is submitted or an already submitted entry is explicitly edited/deleted.
After an open ticket is selected, the stored client name becomes read-only for
that job everywhere, including Work in Progress and Review.
After an authenticated lookup, Work in Progress and Review show **Ticket
notes** and **Past time entries** buttons when the selected ticket has usable
history, or disabled **No Notes** and **No past entries** buttons when none is
available. Service Desk Notification ticket notes, notes with titles that
start with Workflow Rule, and notes with titles that start with Some actions
did not occur are treated as system noise and filtered out. Notes are shown
newest first with two-line title cards. Past time entries list the
resource, local start/stop time, and hours, and selecting one shows its summary
of work. On phones, these buttons sit under the selected Ticket name on Work in
Progress and under Ticket number on Review.
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
to the previous or next day, and tapping the displayed day opens the app's
calendar chooser with **Today**, **Cancel**, and **Set** controls. Today,
yesterday, and tomorrow are labeled like `Today (Saturday)`;
other dates show the full month, ordinal day, and weekday, such as
`June 19th (Friday)`, without the year.
Each service-call choice shows the client name, the detected `Remote` or
`On-Site` value from the service-call details text, the local start/end time
range such as `4:00pm-5:00pm`, and the associated ticket title. Remote and
On-Site cards use stronger distinct accent colors and badges so scheduled call
type is easy to scan without wasting mobile screen space.
Service-call options are filtered by local Job Logger history for the current
managed user: if that user already has a job for the same ticket number with the
editable local ticket status set to `Complete` or `Follow up`, the service call
is hidden even when that time entry has not yet been submitted to Autotask. The
start endpoint applies the same filter before accepting a submitted service-call
ID.
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
scanning. Active Work in Progress cards show an editable **Job date** calendar
with `(Today)`, `(Yesterday)`, or `(Tomorrow)` inside the date box when
applicable, and changing it saves the selected local work date before Review or
submission. Other dates show only the selected date. Active cards also use distinct slot
shading so two active jobs are easier to distinguish. Work in Progress and
Review start/end time fields open a 15-minute time dropdown centered on the
currently selected time while still allowing the `-15` and `+15` step buttons.
Full-browser Work in Progress and Review detail cards group **Entry type** with
**Work type**, **Ticket status** with **Job date**, and **Start time** with
**End time**, with duration centered beneath the time row. Paired full-browser
Review detail cards split their rows evenly, while full-width detail rows stay
full width. Work in Progress also keeps **Client name** and **Ticket name**
together on one row once a ticket is selected, then shows **Ticket number**
full width with ticket-history buttons under the number. **Ticket description**
stays full width.
The full-browser
active-card finish/delete row sits directly below the **Record** and
**AI Cleanup** row with recording and cleanup status text below all action
buttons. On phone-sized Review detail, Record and AI Cleanup status text also
stays below the Review action buttons. Phone-sized authenticated layouts hide
the brand mark and desktop logout button. Managed web users see Work and
Review left-aligned, then Help, Config, optional Diagnostics, and logout
right-aligned. The Work icon links to `/home` and uses the same work-entry
symbol as the full-browser Work nav button. The config super admin sees Users
and Review on the left, with Help, Diagnostics, and logout on the right. Phone
nav icons use one larger shared size inside the compact buttons. The mobile logout
icon submits the normal CSRF-protected `/logout` form. Full-width `/home`,
review, debug, and other non-mobile pages keep the explicit desktop logout
button. Mobile submit actions show a loading overlay once the
tap is accepted so slow redirects or Autotask lookups do not look like ignored
buttons; rounded start/stop `-15` and `+15` adjustments skip the full-page
overlay so those small time changes feel immediate.
Work in Progress and Review detail show the rounded duration centered under the
start/end time controls. The value updates as those times change.
Each Work in Progress card can switch between **Time entry** and **Ticket note**
before Autotask submission. Ticket note mode changes **Job date** to **Note
Date**, hides the start/end time controls while remembering their values, hides
the duration, keeps Work type visible as a disabled greyed-out Remote/On-Site
card, shows a centered required note-title field above the note description,
and changes the finish/delete labels to note wording. Shared switch pills use
green for Time entry or Remote selections and orange for Ticket note or On-Site
selections. Both time entries and notes include an
**Append to resolution** checkbox, checked by default.
In active mobile Work in Progress cards, **End Work**, **End Note**, or the
direct-submit variant shares a row with the destructive delete action to keep
the active-card controls compact, with save, recording, and AI Cleanup status
messages directly below the action buttons. Active jobs selected on Review
detail also show the matching end/delete labels, and the button returns to that
review detail after the job is ended.
The app also queries `Tickets` by `ticketNumber`, creates either a
`TimeEntries` row or a customer-visible `TicketNotes` row, and records every
attempt in `submission_attempts`.

After a job is successfully submitted to Autotask, ticket and client identity
stay read-only, and the entry type can no longer be changed. The selected
review detail allows job date, start time, end time, summary notes, work
location, append-to-resolution, and ticket status edits for time entries
through **Submit changes**, which patches the existing `TimeEntries` row
instead of creating a duplicate entry. For ticket notes, **Submit changes**
updates the existing `TicketNotes` row with note title, note description,
append-to-resolution, and ticket status. **Submit changes** also patches
`Tickets.status` to match the selected Job Logger status, including temporarily
moving a previously `Complete` ticket to `In progress` before the external
record patch when Autotask requires that sequence. Phone-sized workflow cards
use the same scan order on Review and Work in Progress: Entry type, Work type,
Ticket status, Job date, Start time, End time, then duration. The selected
Review detail then shows Ticket number and its ticket-history buttons before
Ticket description. The selected detail keeps the external Autotask record ID
hidden because it is only needed internally for updates and deletion.
The same submitted detail also has **Delete From Autotask**, which deletes the
existing Autotask record and returns the local job to review without
removing the local job record. If Autotask refuses the delete, the job remains
submitted and the safe failure message is shown in review. The selected detail
then shows a dialog that can purge the local Job Logger review entry only; that
fallback warns that the Autotask record may still exist.
Save, accept/resend, retry, ticket selection, entry-type conversion, and local
delete cleanup remain blocked for submitted jobs. The local delete action may
remove active or other unsubmitted local jobs from the selected review detail
when the logged-in managed web user owns the job.

The selected job's audit timeline is collapsed by default and can be expanded
from the review detail when troubleshooting or checking history. Automatic
summary-note autosaves are not shown there; the timeline focuses on explicit
job workflow, transcription, review decisions, submission, and cleanup actions.
Successful Autotask submissions appear as their own job activity.

The mobile Work in Progress card stores a work-location mode of `Remote` or
`On-Site` for time entries, defaulting to `Remote`. This mode does not appear
in the mobile summary text. The review list shows each time entry's Remote or
On-Site mode and shows Ticket note for notes. Review detail keeps the
Remote/On-Site Work type card visible but disabled for Ticket notes, and allows
the choice to be changed only for time entries. Changing it updates the visible
Autotask-bound summary prefix, such as `Remote. Replaced firewall` or
`On-Site. Replaced firewall`, so the prefix can be corrected before submission
or **Submit changes**. Ticket-note descriptions remain unprefixed. The server
parses time-entry prefixes back into the stored work-location mode and keeps
local note storage unprefixed.

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

The `/debug` page is available to the config super admin and to managed web
users marked Admin on `/users`. Managed admins get the same Diagnostics buttons
and options, but no `/users` access, no super-admin review scope, and no extra
job workflow permissions. Non-admin managed users do not see the Diag menu
item, and direct `/debug/*` requests from those sessions return 403. It shows
the source-controlled application version and includes **Test Autotask API**
and **Log out web users** buttons. The logout button forces all managed web
users to sign in again while leaving the config super admin signed in; a
managed admin who clicks it is included because that account is a managed web
user. The authenticated desktop navigation labels this route as **Diag**, while
the page title remains **Diagnostics**. All authenticated pages also include a
Help button that opens `/help`; the Help page opens release notes with
**version changelog**. The Diagnostics Autotask check verifies
required workflow configuration and the live Companies/Tickets API calls used
by the app. The **Test Autotask API** button is manual and always runs a fresh
live check. It is not used by the
initial mobile page or blank Start Work route.
When cached app health is degraded, every signed-in user sees an exclamation
status button in the top bar that opens `/help#operational-status`. It is
yellow for warning and red for critical, while specific Diagnostics details
remain limited to Diagnostics-authorized users. It appears for conditions such
as low disk space, unavailable database connectivity, high database query
latency, high database connection pool pressure, active local login protection
or app-managed Cloudflare IP blocks, or a cached Autotask API failure.
Autotask failures from any managed user, managed Admin user, or config super
admin keep the button visible until the same type of Autotask operation
succeeds again. Successful unrelated Autotask requests do not clear another
active failure. The top of Diagnostics also shows a yellow warning banner or
red critical banner while any monitored
app-health issue is active.

The same `/debug` page also shows compact, paginated successful-login,
failed-login, Cloudflare blocked-IP, and Autotask submission-attempt windows.
Successful-login, failed-login, and Autotask submission-attempt lists show 7
rows per page without vertical table scrollbars, while Cloudflare blocked IPs
show 10 rows per page. Successful and failed local app login attempts are
stored as sanitized `login_attempts` database rows. The Diagnostics tables and
downloads include timestamp, client IP, proxy header details, username, user
agent, request path, host/proxy metadata, account kind, authentication method,
failure reason, and password-present/length metadata for failures. Nginx
replaces incoming forwarded client headers with one sanitized client IP before
proxying to the app. Diagnostics show that client IP plus the supporting proxy
metadata, while local lockout and Cloudflare blocking use the trusted
enforcement IP instead of display-only request headers.
On phone layouts, wide Diagnostics tables scroll horizontally so row details and
actions remain reachable without squeezing every column into the viewport.
Successful-login rows use a yellow account chip for the config super admin, a
green chip for managed web users, and colored `Password` or `Passkey` method
pills.
The raw submitted password is never stored or displayed. The
`/debug/logs/login-failures` and `/debug/logs/login-successes` endpoints
generate sanitized JSONL downloads from the database for authenticated
diagnostics.
Password reset audit events store only safe metadata such as hashed submitted
email identifiers, user IDs when a unique enabled account was matched, reset row
IDs, delivery status, and rate-limit results. They never store raw reset tokens,
full reset URLs, submitted passwords, SMTP secrets, Turnstile secrets, cookies,
or authorization headers.

Failed-login rows can be hidden from the `/debug` table by setting a hidden
timestamp on the database row. When `CLOUDFLARE_IP_BLOCKING_ENABLED=true` and
`CLOUDFLARE_API_TOKEN` plus `CLOUDFLARE_ZONE_ID` are configured, `/debug` can
create and remove app-managed Cloudflare zone IP Access Rules for failed-login
client IPs. Diagnostics can also add a manual Cloudflare IP block with a
reason. Failed-login row blocks, manual blocks, and automatic blocks are stored
locally with their reason and use only app-managed Cloudflare rules. Job Logger
automatically creates a Cloudflare block after
`CLOUDFLARE_AUTO_BLOCK_FAILED_LOGIN_ATTEMPTS` consecutive failed local logins
from the same trusted enforcement IP and submitted username, defaulting to 5.
The same threshold locally blocks further password or Device sign-in
verification for `LOGIN_LOCAL_LOCKOUT_MINUTES`, defaulting to 15. A successful
password or Device sign-in login for that IP and username resets the counter to
zero first.
`CLOUDFLARE_IP_BLOCK_ALLOWLIST` accepts trusted IPs or CIDRs separated by
commas or whitespace so home/admin addresses are never app-blocked.

The `/debug` page also includes a **Disk space** card for the app-visible root
filesystem and `AUTOMATIC_BACKUP_DIR`. Paths with exactly matching used and
total space are combined into one row because they are reporting the same
underlying storage. The card warns at 85% used or under 5 GB free, and becomes
critical at 95% used or under 1 GB free. In Docker this reflects storage visible
from the app container; monitor PostgreSQL storage separately unless that
storage is also exposed to the app container.

Diagnostics includes a **Database** card with safe connectivity status, query
latency, backend/driver, migration revision, and connection-pool counters. It
intentionally hides connection strings, hosts, usernames, passwords, and raw
database errors.

Job Logger can send best-effort Pushover notifications to an administrator
when monitored app health first degrades, when the active degraded issue set
changes, and when all monitored checks are restored. Enable this with
`PUSHOVER_ENABLED=true`, `PUSHOVER_USER_KEY`, and `PUSHOVER_APP_KEY`.
When `DEV_BUILD=true`, Job Logger suppresses Pushover notifications regardless
of `PUSHOVER_ENABLED` so dev/test deployments do not alert as production.
The monitor runs inside the app process at
`APP_HEALTH_MONITOR_INTERVAL_SECONDS` and uses the same disk, cached Autotask,
database status, database latency, database connection-pool pressure, and login
protection signals shown by Diagnostics. It does not replace an external
uptime monitor: if the host, container, network path, or app process is fully
down, the app cannot send its own Pushover message. Use an external monitor
against `/health/live` for full unavailability alerts.

Application logs go to stdout/stderr for standalone Compose compatibility. Use
`docker compose logs app` or the configured container log driver for
operational log history. In Swarm, `docker-swarm.yml` also sets `LOG_DIR` to
`/data/logs`, backed by the shared storage path's `logs/app/` directory, so the
redacted app log is also written to `job-logger-app.log`. `LOG_LEVEL` controls
both stdout/stderr and file-log verbosity and must be one of `DEBUG`, `INFO`,
`WARNING`, or `ERROR`.

The app also creates automatic full-database backups at startup and then every
hour when `AUTOMATIC_BACKUPS_ENABLED=true`, which is the default. Docker Compose
stores them in `${AUTOMATIC_BACKUP_DIR:-/data/backups}`, backed by the
`automatic_backups` Docker volume. Docker Swarm stores them in the shared
`${JOB_LOGGER_SWARM_STORAGE_PATH:-/mnt/swarm-storage/job-logger}/backups`
directory. Retention keeps the newest 6 hourly backups plus one daily backup
for today and one for each of the prior 2 days; expired automatic backups are
purged after each successful automatic backup.
Diagnostics labels retained automatic backups as `Startup` or `Hourly` when
that creation metadata is available; older retained files may show no source
label.

The `/debug` page also includes **Download Full Backup** and **Restore Full
Backup** controls. Each retained automatic backup also has a per-file
**Download** button. Backups are sensitive `.json.gz` files containing all Job
Logger database tables, including managed web-user password hashes and email
metadata, jobs, sanitized login attempts, submission attempts, and audit events.
Store backup files
somewhere private because they contain account, customer, ticket, and
work-summary history.

To restore, upload a Job Logger full-backup file on `/debug` and type
`RESTORE`. Restore validates the archive format, required tables, and columns
before deleting current app rows. A successful restore replaces the current app
database contents with the backup contents, then records a new restore audit
event. Backups from v1.0.2 that predate the **Submit from Work in Progress**
preference restore with that new option defaulted off. Backups that predate the
managed-user session invalidation column restore with no users forced out by
that missing column. Backups that predate ticket-note entry mode restore jobs
as time entries with **Append to resolution** defaulted on and no note title.
The default restore upload cap is 250 MB:
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

When Autotask rejects `TimeEntries` or `TicketNotes` creation/update, Job
Logger surfaces bounded body-level error details when Autotask provides them.
This usually identifies the specific missing permission, invalid role, billing
code, resource, or required field more clearly than a generic HTTP 500 message.
If the error names ticket status updates or `Tickets.status`, confirm the API
user has ticket workflow permissions and that the `AUTOTASK_STATUS_*_ID` values
match the tenant picklist IDs.

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
duration. Work in Progress rounded start and rounded stop use editable 12-hour
time fields like Review detail start and end time, plus `-15` and `+15`
controls and a 15-minute dropdown that opens around the currently selected
time; the server still rounds, validates, and saves those active-job edits.
Work in Progress and Review detail show that rounded duration as centered labels
like `15 Minutes`, `1 Hour`, or `1.25 Hours`.
Work shows centered compact boxed total time-entry hours worked today and this
week.
Review shows today and week total cards, lists jobs newest-first, 10 rows per
page, and includes day-hours and week-hours columns for each job owner/date.
Ticket notes do not add to hour totals because they do not record time.
Time entries also enforce work-location minimums: Remote work must be at least
15 rounded minutes, and On-Site work must be at least 1 rounded hour. Ticket
notes do not use start and end times, so these minimums do not apply to notes.
Review detail shows the active Work in Progress rounded stop preview when an
active job is selected, but review save ignores that displayed end time until
the user actually ends the job. Ended review edits must explicitly choose a
valid later end time on the same job date.

## Ticket Numbers

The mobile page starts jobs without ticket or client fields. After work starts,
select a client from Autotask company search on the active job card, then choose
an open Autotask ticket from the returned list. The ticket number is not
manually editable on mobile; the open-ticket selection fills and saves it
automatically.

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
