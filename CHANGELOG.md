# Changelog

All recorded changes to Job Logger are documented in this file.

## Unreleased

- Added the initial `AGENTS.md` project instructions for the Dockerized Python
  Job Logger application.
- Documented the security-first architecture, Cloudflare Tunnel deployment
  expectations, PostgreSQL storage requirements, Autotask review workflow,
  speech-to-text provider configurability, time rounding rules, audit logging
  requirements, Python standards, and changelog policy.
- Created the initial FastAPI application, Docker stack, PostgreSQL/Alembic
  schema, mobile capture page, desktop review page, speech-to-text provider
  interface, Autotask provider interface, CSRF-protected local authentication,
  audit logging, and tests.
- Replaced the OpenAI speech-to-text provider with local faster-whisper
  transcription and updated Docker/environment variables for local model
  caching.
- Made the `cloudflared` Docker service part of the default Compose stack,
  required `CLOUDFLARE_TUNNEL_TOKEN` for startup, restricted local app and
  tunnel metrics ports to `127.0.0.1`, and updated tunnel deployment
  documentation.
- Added tunnel 502 troubleshooting documentation and a `/moble` typo redirect
  to the mobile page.
- Added a tunnel diagnostic script and clarified that Cloudflare Tunnel should
  route to `http://app:8000` when `cloudflared` runs in the Compose stack,
  regardless of the host-side `APP_EXPOSE_PORT` value.
- Added `APP_INTERNAL_PORT` so the Uvicorn/container port can be changed from
  the default `8000` without confusing it with the host-side
  `APP_EXPOSE_PORT` mapping.
- Added an Nginx reverse-proxy container as the web front end for Cloudflare
  Tunnel, moved host troubleshooting traffic to Nginx, and updated tunnel
  diagnostics to validate `cloudflared -> nginx -> app` connectivity.
- Split Nginx self-health from FastAPI upstream health so Compose can start the
  reverse proxy reliably while still keeping explicit diagnostics for
  `nginx -> app` connectivity.
- Relaxed compose startup when a Cloudflare tunnel token is missing by moving the
  token requirement into container runtime checks and documenting a local debug
  path that runs `app`, `db`, and `nginx` without tunnel connectivity.
- Updated Nginx health checks to avoid false unhealthy states when optional
  network tools are absent inside the container image.
- Updated `cloudflared` compose command handling to work with Cloudflare's
  distroless image (no `/bin/sh`) and added a fallback tunnel-token value so
  startup logs remain actionable when the token is not set.
