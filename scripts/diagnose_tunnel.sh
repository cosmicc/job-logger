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
NGINX_PUBLIC_PORT="$(get_non_secret_setting "NGINX_PUBLIC_PORT" "11030")"
CLOUDFLARE_TUNNEL_TOKEN="$(get_non_secret_setting "CLOUDFLARE_TUNNEL_TOKEN" "")"

printf '%s\n' "Job Logger tunnel diagnostics"
printf '%s\n' "============================="

printf '\n%s\n' "1. Docker Compose service state"
docker compose ps

printf '\n%s\n' "2. Nginx self-health through the host troubleshooting port"
if curl -fsS "http://127.0.0.1:${NGINX_PUBLIC_PORT}/nginx-health" >/dev/null; then
    printf '%s\n' "Host Nginx self-health check passed."
else
    printf '%s\n' "Host Nginx self-health check failed. Nginx is not reachable on 127.0.0.1:${NGINX_PUBLIC_PORT}."
fi

printf '\n%s\n' "3. App health through the Nginx host troubleshooting port"
if curl -fsS "http://127.0.0.1:${NGINX_PUBLIC_PORT}/health/live"; then
    printf '\n%s\n' "Nginx-to-app proxy health check passed from the host."
else
    printf '\n%s\n' "Nginx is reachable, but the app health route did not pass through Nginx."
fi

printf '\n%s\n' "4. Mobile route through the Nginx host troubleshooting port"
curl -i "http://127.0.0.1:${NGINX_PUBLIC_PORT}/mobile" || true

printf '\n%s\n' "5. App health from inside the app container"
if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()" >/dev/null; then
    printf '\n%s\n' "App container health check passed."
else
    printf '\n%s\n' "App container health check failed. Container cannot serve http://127.0.0.1:8000/health/live."
fi

printf '\n%s\n' "6. Cloudflared runtime and token state"
docker compose ps cloudflared
if [ -z "${CLOUDFLARE_TUNNEL_TOKEN}" ]; then
    printf '%s\n' "CLOUDFLARE_TUNNEL_TOKEN is not set in environment."
elif [ "${CLOUDFLARE_TUNNEL_TOKEN}" = "not-set" ]; then
    printf '%s\n' "CLOUDFLARE_TUNNEL_TOKEN was expanded to 'not-set' in compose."
else
    printf '%s\n' "CLOUDFLARE_TUNNEL_TOKEN is set."
fi
printf '%s\n' "Cloudflared is configured to use origin: http://127.0.0.1:${NGINX_PUBLIC_PORT}."
printf '%s\n' "Recent cloudflared logs:"
docker compose logs --tail=80 cloudflared
