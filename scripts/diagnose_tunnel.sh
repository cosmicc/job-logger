#!/usr/bin/env sh
set -eu

# This script intentionally prints only connectivity and status information.
# It does not print environment variables because the tunnel token and app
# secrets must remain private.

# The host port is only for local troubleshooting from the Docker host.
APP_EXPOSE_PORT="${APP_EXPOSE_PORT:-11030}"

printf '%s\n' "Job Logger tunnel diagnostics"
printf '%s\n' "============================="

printf '\n%s\n' "1. Docker Compose service state"
docker compose ps

printf '\n%s\n' "2. App health through the host troubleshooting port"
if curl -fsS "http://127.0.0.1:${APP_EXPOSE_PORT}/health/live"; then
    printf '\n%s\n' "Host health check passed."
else
    printf '\n%s\n' "Host health check failed. The app is not reachable on 127.0.0.1:${APP_EXPOSE_PORT}."
fi

printf '\n%s\n' "3. App route through the host troubleshooting port"
curl -i "http://127.0.0.1:${APP_EXPOSE_PORT}/mobile" || true

printf '\n%s\n' "4. App health from inside the cloudflared container"
if docker compose exec -T cloudflared wget -qO- "http://app:8000/health/live"; then
    printf '\n%s\n' "Container-to-container health check passed. Cloudflare Tunnel should use http://app:8000."
else
    printf '\n%s\n' "Container-to-container health check failed. cloudflared cannot reach the app container as http://app:8000."
fi

printf '\n%s\n' "5. Recent cloudflared logs"
docker compose logs --tail=80 cloudflared
