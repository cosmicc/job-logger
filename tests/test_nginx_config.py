"""Regression tests for the public nginx reverse-proxy surface."""

from __future__ import annotations

from pathlib import Path

NGINX_TEMPLATE = Path(__file__).resolve().parents[1] / "docker/nginx/templates/default.conf.template"
NGINX_DOCKERFILE = Path(__file__).resolve().parents[1] / "docker/nginx/Dockerfile"
NGINX_ERROR_DIR = Path(__file__).resolve().parents[1] / "docker/nginx/errors"
COMMON_ERROR_CODES = ("400", "401", "403", "404", "405", "408", "413", "429", "500", "502", "503", "504")


def test_nginx_blocks_public_api_and_health_paths() -> None:
    """Internet-facing nginx should not proxy API, schema, docs, or health paths."""

    template_text = NGINX_TEMPLATE.read_text(encoding="utf-8")

    blocked_locations = (
        "location = /nginx-health",
        "location = /health",
        "location ^~ /health/",
        "location = /api",
        "location ^~ /api/",
        "location = /openapi.json",
        "location ^~ /docs",
        "location ^~ /redoc",
    )
    for location in blocked_locations:
        location_index = template_text.index(location)
        block_end_index = template_text.index("\n    }", location_index)
        location_block = template_text[location_index:block_end_index]
        assert "return 404;" in location_block
        assert "proxy_pass" not in location_block


def test_nginx_uses_app_styled_error_pages() -> None:
    """Proxy-generated errors should use Job Logger pages without server branding."""

    template_text = NGINX_TEMPLATE.read_text(encoding="utf-8")
    dockerfile_text = NGINX_DOCKERFILE.read_text(encoding="utf-8")

    assert "server_tokens off;" in template_text
    assert "location ^~ /errors/" in template_text
    assert "internal;" in template_text
    assert 'add_header Cache-Control "no-store" always;' in template_text
    assert "COPY errors/ /usr/share/nginx/html/errors/" in dockerfile_text

    for error_code in COMMON_ERROR_CODES:
        assert f"error_page {error_code} /errors/{error_code}.html;" in template_text
        error_page = NGINX_ERROR_DIR / f"{error_code}.html"
        error_html = error_page.read_text(encoding="utf-8")
        assert f"Error {error_code}" in error_html
        assert "Job Logger web service" in error_html
        assert "nginx" not in error_html.lower()
        assert "<title>" in error_html
        assert "<h1>" in error_html
        assert "<p>" in error_html


def test_nginx_restore_upload_limit_is_scoped_to_restore_endpoint() -> None:
    """Full restore can use a larger body limit without widening every route."""

    template_text = NGINX_TEMPLATE.read_text(encoding="utf-8")
    restore_location_index = template_text.index("location = /debug/restore")
    restore_block_end_index = template_text.index("\n    }", restore_location_index)
    restore_block = template_text[restore_location_index:restore_block_end_index]

    assert "client_max_body_size ${NGINX_RESTORE_MAX_BODY_SIZE};" in restore_block
    assert "proxy_pass http://${APP_UPSTREAM_HOST}:8000/debug/restore;" in restore_block
    assert template_text.count("NGINX_RESTORE_MAX_BODY_SIZE") == 1


def test_nginx_preserves_forwarded_https_scheme_for_app_origin() -> None:
    """Cloudflare's public HTTPS scheme should reach FastAPI for passkey verification."""

    template_text = NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "map $http_x_forwarded_proto $job_logger_forwarded_proto" in template_text
    assert '"" $scheme;' in template_text
    assert "proxy_set_header X-Forwarded-Proto $job_logger_forwarded_proto;" in template_text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" not in template_text


def test_nginx_replaces_spoofable_forwarded_for_with_tunnel_client_ip() -> None:
    """Nginx should not pass through attacker-supplied X-Forwarded-For chains."""

    template_text = NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "map $http_cf_connecting_ip $job_logger_client_ip" in template_text
    assert '"" $remote_addr;' in template_text
    assert "proxy_set_header X-Forwarded-For $job_logger_client_ip;" in template_text
    assert "proxy_set_header X-Real-IP $job_logger_client_ip;" in template_text
    assert "$proxy_add_x_forwarded_for" not in template_text
