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
   http://nginx:8080
   ```

3. Create a Cloudflare Access self-hosted application for that hostname.
4. Put the same hostname in `.env` under `APP_ALLOWED_HOSTS`.
5. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
6. Set `CLOUDFLARE_ACCESS_REQUIRED=true` after Access is verified.
7. Start the full stack:

   ```bash
   docker compose up -d --build
   ```

Nginx is the internal web front end for this deployment. Public mobile and
review traffic should enter through the Cloudflare Tunnel hostname, reach the
internal Docker service `http://nginx:8080`, and then proxy to FastAPI at
`http://app:8000`.

The app container is exposed only to the private Compose network. The local
troubleshooting URL reaches Nginx on `127.0.0.1`, not the app container
directly.

`APP_INTERNAL_PORT` changes the Uvicorn port inside the app container and inside
the Docker network. The default is `8000`. Nginx uses this value to reach the
FastAPI app.

```text
APP_INTERNAL_PORT=8010 -> Nginx proxies to http://app:8010
```

`NGINX_INTERNAL_PORT` changes the private Compose-network port that
`cloudflared` should use. The default is `8080`. If you change it, update the
Cloudflare public hostname service URL to match:

```text
NGINX_INTERNAL_PORT=8081 -> Cloudflare service URL http://nginx:8081
```

`NGINX_EXPOSE_PORT` changes only the optional host-side troubleshooting port.
For example, the defaults create this mapping:

```text
Docker host 127.0.0.1:11030 -> nginx container port 8080 -> app container port 8000
```

If `cloudflared` is not running in this Compose stack, it will not be able to
resolve the Docker service name `nginx`. In that separate-deployment case,
either move `cloudflared` into this Compose stack or point the tunnel at the
actual host-reachable Nginx URL.

The `cloudflared` metrics endpoint is published only on localhost at
`127.0.0.1:20241` by default so tunnel diagnostics can be collected from the
Docker host without exposing metrics to the network.

### Tunnel 502 Troubleshooting

A Cloudflare 502 means the request reached Cloudflare and the tunnel connector,
but `cloudflared` could not reach the origin service configured for the public
hostname.

Check these items first:

- Confirm `.env` exists and contains a real `CLOUDFLARE_TUNNEL_TOKEN`.
- Confirm the Cloudflare public hostname service URL is exactly
  `http://nginx:8080` when `NGINX_INTERNAL_PORT=8080`, or
  `http://nginx:<your-nginx-internal-port>` if you changed
  `NGINX_INTERNAL_PORT`.
- Do not use `http://localhost:<port>` or `http://127.0.0.1:<port>` in the
  Cloudflare public hostname service URL. Inside the `cloudflared` container,
  localhost means the tunnel container itself, not Nginx or FastAPI.
- Confirm Nginx can reach the app from the Docker host:

  ```bash
  curl -i http://127.0.0.1:11030/health/live
  ```

- Confirm Nginx is healthy from inside the tunnel container:

  ```bash
  docker compose exec cloudflared wget -qO- http://nginx:${NGINX_INTERNAL_PORT:-8080}/health/live
  ```

- Confirm the app is healthy from inside the Nginx container:

  ```bash
  docker compose exec nginx wget -qO- http://app:${APP_INTERNAL_PORT:-8000}/health/live
  ```

- Review tunnel connector logs:

  ```bash
  docker compose logs --tail=100 cloudflared
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
