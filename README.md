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
- Cloudflare Access should protect the public hostname before the app login page.
- Configurable providers support mock or live speech-to-text and Autotask modes.

Cloudflare documents Tunnel as an outbound `cloudflared` connector and Access as
the control point for self-hosted applications:

- https://developers.cloudflare.com/tunnel/setup/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/

Autotask REST API references used by this app:

- TimeEntries entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TimeEntriesEntity.htm
- Tickets entity: https://www.autotask.net/help/developerhelp/Content/APIs/REST/Entities/TicketsEntity.htm
- REST authentication headers: https://www.autotask.net/help/developerhelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm

## Local Setup

1. Create an environment file:

   ```bash
   cp .env.example .env
   ```

2. Generate a password hash:

   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -e ".[dev]"
   python -m job_logger.security hash-password 'replace-this-password'
   ```

3. Put the generated hash in `.env` as `APP_PASSWORD_HASH`.

4. Replace `APP_SECRET_KEY` with a long random value.

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

3. Create a Cloudflare Access self-hosted application for that hostname.
4. Put the same hostname in `.env` under `APP_ALLOWED_HOSTS`.
5. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
   If this token is missing or invalid, Cloudflare will return a 502 and
   `cloudflared` will repeatedly restart.
6. Set `CLOUDFLARE_ACCESS_REQUIRED=true` after Access is verified.
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

The Docker Compose stack stores faster-whisper model files in the
`faster_whisper_models` volume mounted at `/models/faster-whisper`. This keeps
the model local and avoids redownloading it on every container restart.
Set `FASTER_WHISPER_LOCAL_FILES_ONLY=true` after the model exists locally if the
container should not attempt any model download.

`TRANSCRIPTION_PROVIDER=mock` proves the upload path without loading a local
model. `TRANSCRIPTION_PROVIDER=disabled` rejects transcription attempts.

Raw audio is not stored by default. The app reads the upload into memory, sends
it to the local provider through a temporary file, deletes that temporary file,
and stores only the returned text and safe status.

### Autotask

`AUTOTASK_PROVIDER=mock` is the default and creates a local mock external ID.

`AUTOTASK_PROVIDER=autotask` enables live REST API calls. Set:

- `AUTOTASK_BASE_URL`
- `AUTOTASK_USERNAME`
- `AUTOTASK_SECRET`
- `AUTOTASK_API_INTEGRATION_CODE`
- `AUTOTASK_RESOURCE_ID`
- `AUTOTASK_ROLE_ID`

Autotask ticket status picklist IDs vary by tenant. Configure these when live
ticket-status updates should be sent:

- `AUTOTASK_STATUS_IN_PROGRESS_ID`
- `AUTOTASK_STATUS_WAITING_CUSTOMER_ID`
- `AUTOTASK_STATUS_WAITING_PARTS_ID`
- `AUTOTASK_STATUS_FOLLOW_UP_ID`
- `AUTOTASK_STATUS_COMPLETE_ID`

The app queries `Tickets` by `ticketNumber`, creates a `TimeEntries` row, and
records every attempt in `submission_attempts`.

## Time Handling

All user-facing dates and times use `America/Detroit`.

All database timestamps are stored in UTC.

Start time, end time, and resulting duration are rounded to 15-minute intervals.
If rounding would produce a zero-minute job, the end time is advanced to the next
15-minute interval.

## Testing

Run local checks with:

```bash
python -m compileall job_logger tests
pytest
ruff check .
docker compose config
```
