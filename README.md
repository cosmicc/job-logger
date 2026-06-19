# Job Logger

Job Logger is a security-focused Dockerized Python web application for quickly
recording work time from a phone, reviewing the recorded jobs from a desktop,
and submitting accepted jobs to Autotask.

## Architecture

- FastAPI serves the application.
- Nginx fronts the FastAPI web interface inside Docker.
- Jinja templates render the mobile capture page and desktop review page.
- PostgreSQL stores jobs, review fields, submission attempts, and audit events.
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
- ServiceCalls entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallsEntity.htm
- ServiceCallTickets entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallTicketsEntity.htm
- ServiceCallTicketResources entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/ServiceCallTicketResourceEntity.htm
- REST authentication headers: https://www.autotask.net/help/developerhelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm

## Local Setup

1. Create an environment file:

   ```bash
   cp .env.example .env
   ```

2. Set `APP_USERNAME` and `APP_PASSWORD` in `.env`.

3. Replace `APP_SECRET_KEY` with a long random value.

4. Start the stack:

   ```bash
   docker compose up -d --build
   ```

   If you do not have a tunnel token yet, run only local services first:

   ```bash
   docker compose up -d --build app db nginx
   ```

5. Open the local troubleshooting URL at:

   ```text
   http://127.0.0.1:11030
   ```

## Cloudflare Tunnel

The Compose file starts Nginx and `cloudflared` by default. This keeps the
production deployment path simple: the app, PostgreSQL, Nginx reverse proxy, and
tunnel connector all come up with one `docker compose up -d --build` command.

1. Create a Cloudflare Tunnel in the Zero Trust dashboard.
2. Add a public hostname that routes to this Docker service URL:

   ```text
   http://<server-internal-ip>:11030
   ```

   For this deployment, that means `http://192.168.199.11:11030` on your
   production network. If `cloudflared` runs on the same Docker host, localhost
   can also work, but the configured service URL must match an address that is
   reachable from the `cloudflared` connector.

3. Optionally create a Cloudflare Access self-hosted application for that hostname.
4. Put the same hostname in `.env` under `APP_ALLOWED_HOSTS`.
5. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
   If this token is missing or invalid, Cloudflare will return a 502 and
   `cloudflared` will repeatedly restart.
6. Leave `CLOUDFLARE_ACCESS_REQUIRED=false` when using only the app's
   `APP_USERNAME` and `APP_PASSWORD` login. Set it to `true` only after
   Cloudflare Access is configured and verified for the public hostname.
7. Start the full stack:

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
Nginx endpoint on `<server-internal-ip>:11030` by default (or
`<server-internal-ip>:<NGINX_PUBLIC_PORT>` after you change it), and then proxy to FastAPI at
`http://app:8000`.

The app container is exposed only to the private Compose network. The local
troubleshooting URL reaches Nginx on `127.0.0.1`, not the app container
directly.

Nginx binds `NGINX_PUBLIC_PORT` on host interfaces so a remotely-managed tunnel
can reach the origin by server IP. Keep host firewall rules limited to trusted
networks or the tunnel connector path because direct LAN access to this port
bypasses Cloudflare Access. Application login still protects the app itself.

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

Nginx exposes two health paths:

- `/nginx-health` checks only the Nginx container.
- `/health/live` proxies through Nginx to the FastAPI app.

The nginx container is built from `docker/nginx/Dockerfile` with this app's
proxy template baked in. If `/nginx-health` returns a stock nginx 404 page, the
running container is not using this project's nginx image/config and should be
rebuilt.

The normal Nginx startup log ends with `Configuration complete; ready for start
up` and `start worker process`. If the log later says `signal 3 (SIGQUIT)
received, shutting down`, Docker or Compose asked Nginx to stop gracefully; that
line is not an Nginx configuration failure by itself.

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
  to reach) is `http://<server-internal-ip>:11030` by default, or your configured
  `NGINX_PUBLIC_PORT`. For the current production network, that is
  `http://192.168.199.11:11030`.
- Confirm Nginx itself is reachable from the Docker host:

  ```bash
  curl -i http://127.0.0.1:11030/nginx-health
  ```

- Confirm Nginx can reach the app from the Docker host:

  ```bash
  curl -i http://127.0.0.1:11030/health/live
  ```

- Confirm Nginx is reachable through the same server IP used by Cloudflare:

  ```bash
  curl -i http://192.168.199.11:11030/nginx-health
  ```

- Confirm the app accepts the Cloudflare public hostname after container
  recreation:

  ```bash
  curl -i -H 'Host: joblogger.lsec.io' http://127.0.0.1:11030/health/live
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

The mobile route is `/mobile`. The app also redirects `/moble` to `/mobile` to
avoid a common typo after the tunnel is working.

## Mobile App Mode

Job Logger includes progressive web app metadata so a phone can install it from
the browser and launch it without the normal browser toolbar.

Use the Cloudflare HTTPS hostname on the phone, sign in, open the browser menu,
and choose the platform's install action such as **Add to Home Screen** or
**Install App**. After launching from that home-screen icon, the app uses
standalone display mode, the configured dark theme color, safe-area padding for
phone status bars, and disabled page overscroll/bounce behavior.

The service worker is intentionally network-only. It supports standalone app
launch behavior but does not cache authenticated pages, job data, Autotask
responses, transcription data, raw audio, or diagnostics.

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

The Docker Compose stack stores faster-whisper model files in the
`faster_whisper_models` volume mounted at `/models/faster-whisper`. This keeps
the model local and avoids redownloading it on every container restart.
Set `FASTER_WHISPER_LOCAL_FILES_ONLY=true` after the model exists locally if the
container should not attempt any model download.
`FASTER_WHISPER_CPU_THREADS` defaults to `8` and is passed directly to
faster-whisper's local model loader. `FASTER_WHISPER_MEMORY_LIMIT` defaults to
`8g` and controls the Docker Compose memory limit for the app container, where
local transcription runs.
For reliable local transcription, run the Docker stack on a server with at least
8 CPU cores and 10 GB of RAM so the app container can use its default 8-thread,
8 GB faster-whisper allocation while leaving memory for PostgreSQL, Nginx, and
the host operating system.

`TRANSCRIPTION_PROVIDER=mock` proves the transcription path without loading a
local model. `TRANSCRIPTION_PROVIDER=disabled` rejects transcription attempts.

The mobile recorder streams `MediaRecorder` chunks to
`WebSocket /jobs/{job_id}/description/audio/stream`. The first WebSocket
message carries metadata and the CSRF token, then binary audio chunks are sent
as soon as the browser produces them. The server starts a best-effort interim
transcription from the first buffered chunk. The mobile **Record Audio** button
becomes a red **Stop recording** button while browser capture is active.
Stopping capture lets the browser flush the final chunk, sends WebSocket
`finish`, returns the button to its idle appearance, and keeps showing
transcode/transcription status until the final saved transcript or a bounded
error response returns.

Raw audio is not stored by default. The app keeps the streamed recording in
memory only, sends buffered bytes to the local provider through a temporary
file, deletes that temporary file, and stores only the returned text and safe
status. The existing `MAX_AUDIO_UPLOAD_BYTES` setting also limits streamed
recordings.

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
- `AUTOTASK_RESOURCE_ID`
- `AUTOTASK_ROLE_ID`

Autotask ticket status picklist IDs vary by tenant. Configure these before
production use so the full workflow can update the selected ticket status:

- `AUTOTASK_STATUS_IN_PROGRESS_ID`
- `AUTOTASK_STATUS_WAITING_CUSTOMER_ID`
- `AUTOTASK_STATUS_WAITING_PARTS_ID`
- `AUTOTASK_STATUS_FOLLOW_UP_ID`
- `AUTOTASK_STATUS_COMPLETE_ID`

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
path. Start Work uses a separate short Autotask health cache: successful checks
are reused for five minutes, and failures are reused for thirty seconds. Live
company and ticket queries request `MaxRecords=500` and follow Autotask
pagination links so larger tenants are not limited to the first page of results.
Pagination is bounded and fails safely instead of silently showing partial
customer or ticket lists. For POST query pagination, Job Logger follows
`nextPageUrl` with POST and the original query body because Autotask rejects GET
follow-up calls for those resources.

The mobile and review pages can query open Autotask tickets from the selected
job's stored company ID or stored client name. On mobile, the **Find tickets**
button saves the current active-job client fields before loading open tickets,
and saved clients auto-load the list when the Work in Progress card renders.
Selecting a returned ticket fills the mobile job's hidden ticket number, stores
the selected ticket title for the review detail heading, stores the bounded
ticket description for read-only context, and automatically saves the active-job
changes or review ticket selection. The mobile Work in Progress card shows the
selected ticket number, ticket name, and ticket description after selection. On
the review page, the stored ticket number, ticket description, and client name
are read-only identity/context fields; review save and submit use the stored
values instead of trusting form posts. Once a job has a ticket number, the
open-ticket picker is hidden for that job.

When an active job slot is available, the mobile start panel also lists today's
Autotask service calls assigned to `AUTOTASK_RESOURCE_ID`. Each service-call
choice shows the client name, the detected `Remote` or `On-Site` value from the
service-call details text, and the associated ticket title. Remote and On-Site
cards use distinct accent colors so scheduled call type is easy to scan without
wasting mobile screen space. Tapping a service call starts an active job with
the server-verified ticket number, ticket title, bounded ticket description,
client name, company ID, and detected work-location mode. The browser submits
only the service-call ticket association ID and CSRF token; the server re-checks
today's resource-specific service-call list before creating the job. If service-call
lookup fails because permissions are missing, the blank Start Work path remains
available as long as the normal Autotask start gate is online.

Service-call lookup requires the Autotask API user to read `ServiceCalls`,
`ServiceCallTickets`, and `ServiceCallTicketResources`, in addition to the
Companies and Tickets permissions already required by the app.

The shared page data is styled through `app.css`, then viewport-specific
`phone.css` or `desktop.css` loads automatically with media queries so phones
and desktop browsers get appropriately sized layouts.
The app also queries `Tickets` by `ticketNumber`, creates a `TimeEntries` row,
and records every attempt in `submission_attempts`.

After a job is successfully submitted to Autotask, the review detail becomes
read-only. Save, accept/resend, retry, reject, ticket selection, and force purge
are blocked by the server and removed from the selected-job review UI so the
local record stays aligned with the external time entry.

The mobile Work in Progress card stores a work-location mode of `Remote` or
`On-Site`, defaulting to `Remote`. This mode does not appear in the editable
summary text. When a reviewed job is submitted, the Autotask `summaryNotes`
payload is prefixed with the stored mode, such as `Remote replaced firewall`
or `On-Site replaced firewall`.

Ticket `TimeEntries` payloads intentionally omit `billingCodeID` / Allocation
Code values. Autotask will use the ticket/resource defaults, which avoids
requiring the API resource to have Allocation Code edit permission for ticket
time entries. Existing `AUTOTASK_BILLING_CODE_ID` values in `.env` are ignored
by the submit payload.

Leave `AUTOTASK_IMPERSONATION_RESOURCE_ID` blank unless Autotask specifically
requires impersonation for your tenant. When blank, Job Logger omits the
`ImpersonationResourceId` header and uses the API user's own permissions. If the
value is set, Autotask evaluates Companies/Tickets query permissions for the
impersonated resource context, which can fail even when the API user itself has
access.

The `/debug` page shows the source-controlled application version and includes a
**Test Autotask API** button. That check verifies required workflow
configuration and the live Companies/Tickets API calls used by the app. If the
check fails, new jobs cannot be started until Autotask connectivity or
configuration is fixed. The debug button always runs a fresh live check instead
of using the Start Work health cache.

The `scripts/discover_autotask_ids.py` helper also prints a workflow endpoint
preflight section. Role, billing-code, and ticket-status ID discovery can
succeed even when the Autotask API user cannot query Companies or Tickets, so
use the preflight result and the `/debug` failed-operation label when diagnosing
Autotask HTTP 500 or permission failures. Some Autotask permission denials are
returned as HTTP 500 responses, so check the preflight detail before changing
credentials.

When Autotask rejects ticket status updates or `TimeEntries` creation, Job
Logger surfaces bounded body-level error details when Autotask provides them.
This usually identifies the specific missing permission, invalid role, billing
code, resource, or required field more clearly than a generic HTTP 500 message.

## Time Handling

All user-facing dates and times use `America/Detroit`.

User-facing times display in 12-hour `am`/`pm` format. Review forms also accept
legacy 24-hour submissions so stale browser pages do not fail during deployment.

All database timestamps are stored in UTC.

Start time, end time, and resulting duration are rounded to 15-minute intervals.
If rounding would produce a zero-minute job, the end time is advanced to the next
15-minute interval.

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
