# Job Logger

Job Logger is a security-focused Dockerized Python web application for quickly
recording work time from a phone, reviewing the recorded jobs from a desktop,
and submitting accepted jobs to Autotask.

## Architecture

- FastAPI serves the application.
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
   docker compose up --build
   ```

6. Open the local app at:

   ```text
   http://127.0.0.1:8000
   ```

## Cloudflare Tunnel

The Compose file includes a `cloudflared` service under the `tunnel` profile.

1. Create a Cloudflare Tunnel in the Zero Trust dashboard.
2. Add a public hostname that routes to this Docker service URL:

   ```text
   http://app:8000
   ```

3. Create a Cloudflare Access self-hosted application for that hostname.
4. Put the tunnel token in `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
5. Set `CLOUDFLARE_ACCESS_REQUIRED=true` after Access is verified.
6. Start the tunnel profile:

   ```bash
   docker compose --profile tunnel up --build
   ```

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
