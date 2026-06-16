#!/usr/bin/env sh
set -eu

# This script intentionally prints only connectivity and status information.
# It does not print environment variables because the tunnel token and app
# secrets must remain private.

get_non_secret_setting() {
    variable_name="$1"
    default_value="$2"

    environment_value="$(printenv "${variable_name}" 2>/dev/null || true)"
    if [ -n "${environment_value}" ]; then
        printf '%s\n' "${environment_value}"
        return
    fi

    if [ -f .env ]; then
        dotenv_value="$(
            awk -v name="${variable_name}" '
                $0 ~ "^[[:space:]]*" name "=" {
                    sub("^[[:space:]]*" name "=", "")
                    print
                    exit
                }
            ' .env
        )"
        if [ -n "${dotenv_value}" ]; then
            printf '%s\n' "${dotenv_value}"
            return
        fi
    fi

    printf '%s\n' "${default_value}"
}

# Nginx is the front door for both local troubleshooting and Cloudflare Tunnel.
NGINX_EXPOSE_PORT="$(get_non_secret_setting "NGINX_EXPOSE_PORT" "11030")"
NGINX_INTERNAL_PORT="$(get_non_secret_setting "NGINX_INTERNAL_PORT" "8080")"

# The internal port is where Uvicorn listens inside the app container and where
# Nginx must connect when both services share this Compose network.
APP_INTERNAL_PORT="$(get_non_secret_setting "APP_INTERNAL_PORT" "8000")"

printf '%s\n' "Job Logger tunnel diagnostics"
printf '%s\n' "============================="

printf '\n%s\n' "1. Docker Compose service state"
docker compose ps

printf '\n%s\n' "2. Nginx self-health through the host troubleshooting port"
if curl -fsS "http://127.0.0.1:${NGINX_EXPOSE_PORT}/nginx-health" >/dev/null; then
    printf '%s\n' "Host Nginx self-health check passed."
else
    printf '%s\n' "Host Nginx self-health check failed. Nginx is not reachable on 127.0.0.1:${NGINX_EXPOSE_PORT}."
fi

printf '\n%s\n' "3. App health through the Nginx host troubleshooting port"
if curl -fsS "http://127.0.0.1:${NGINX_EXPOSE_PORT}/health/live"; then
    printf '\n%s\n' "Nginx-to-app proxy health check passed from the host."
else
    printf '\n%s\n' "Nginx is reachable, but the app health route did not pass through Nginx."
fi

printf '\n%s\n' "4. Mobile route through the Nginx host troubleshooting port"
curl -i "http://127.0.0.1:${NGINX_EXPOSE_PORT}/mobile" || true

printf '\n%s\n' "5. Nginx self-health from inside the cloudflared container"
if docker compose exec -T cloudflared wget -qO- "http://nginx:${NGINX_INTERNAL_PORT}/nginx-health" >/dev/null; then
    printf '%s\n' "Container-to-container Nginx self-health check passed. Cloudflare Tunnel should use http://nginx:${NGINX_INTERNAL_PORT}."
else
    printf '%s\n' "Container-to-container Nginx self-health check failed. cloudflared cannot reach Nginx as http://nginx:${NGINX_INTERNAL_PORT}."
fi

printf '\n%s\n' "6. App health from inside the Nginx container"
if docker compose exec -T nginx wget -qO- "http://app:${APP_INTERNAL_PORT}/health/live"; then
    printf '\n%s\n' "Nginx-to-app health check passed."
else
    printf '\n%s\n' "Nginx-to-app health check failed. Nginx cannot reach the app as http://app:${APP_INTERNAL_PORT}."
fi

printf '\n%s\n' "7. Recent cloudflared logs"
docker compose logs --tail=80 cloudflared
