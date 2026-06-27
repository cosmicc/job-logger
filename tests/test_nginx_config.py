"""Regression tests for the public nginx reverse-proxy surface."""

from __future__ import annotations

from pathlib import Path

NGINX_TEMPLATE = Path(__file__).resolve().parents[1] / "docker/nginx/templates/default.conf.template"


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
