"""Regression tests for progressive web app shell metadata."""

from __future__ import annotations

import struct
from pathlib import Path

from fastapi.testclient import TestClient

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_metadata(image_path: Path) -> tuple[int, int, int, int]:
    """Return width, height, bit depth, and color type from a PNG asset."""

    png_bytes = image_path.read_bytes()
    assert png_bytes.startswith(PNG_SIGNATURE)
    assert png_bytes[12:16] == b"IHDR"
    width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(
        ">IIBBBBB",
        png_bytes[16:29],
    )
    assert interlace == 0
    return width, height, bit_depth, color_type


def test_manifest_exposes_standalone_mobile_app_metadata(client: TestClient) -> None:
    """The web app manifest should make the mobile workflow installable."""

    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "TicketPilot"
    assert manifest["start_url"] == "/home"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0b1220"
    icons_by_size = {icon["sizes"]: icon["src"] for icon in manifest["icons"]}
    assert icons_by_size == {
        "128x128": "/static/icons/ticketpilot-app-icon-128.png",
        "256x256": "/static/icons/ticketpilot-app-icon-256.png",
        "512x512": "/static/icons/ticketpilot-app-icon-512.png",
        "1024x1024": "/static/icons/ticketpilot-app-icon-1024.png",
    }
    assert all(icon["type"] == "image/png" for icon in manifest["icons"])
    assert all(icon["purpose"] == "any" for icon in manifest["icons"])


def test_service_worker_is_root_scoped_and_does_not_cache_workflow_data(client: TestClient) -> None:
    """The PWA worker should support install behavior without storing private pages."""

    response = client.get("/service-worker.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["service-worker-allowed"] == "/"
    assert "caches.open" not in response.text
    assert "fetch(event.request)" in response.text


def test_manifest_revalidates_during_icon_testing(client: TestClient) -> None:
    """The manifest should not hold stale mobile install icon paths."""

    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, max-age=0"


def test_base_template_registers_pwa_assets(client: TestClient) -> None:
    """Rendered pages should advertise install metadata and register the worker."""

    response = client.get("/login")

    assert response.status_code == 200
    assert '<link rel="manifest" href="/manifest.webmanifest?v=' in response.text
    assert 'name="mobile-web-app-capable" content="yes"' in response.text
    assert 'name="apple-mobile-web-app-capable" content="yes"' in response.text
    assert 'name="apple-mobile-web-app-status-bar-style" content="black-translucent"' in response.text
    assert 'static/icons/ticketpilot-logo-white.svg?v=' in response.text
    assert 'data-theme-favicon' in response.text
    assert 'static/icons/ticketpilot-app-icon-256.png?v=' in response.text
    assert 'static/pwa.js' in response.text


def test_brand_assets_are_source_controlled_without_superseded_files() -> None:
    """Only the approved logo and app-icon source assets should remain."""

    repository_root = Path(__file__).resolve().parents[1]
    design_dir = repository_root / "docs" / "design"
    assert {path.name for path in design_dir.iterdir() if path.is_file()} == {
        "color_palette.png",
        "theme_palettes.svg",
    }

    static_icon_dir = repository_root / "ticket_pilot" / "static" / "icons"
    assert {path.name for path in static_icon_dir.iterdir() if path.is_file()} == {
        "ticketpilot-logo-white.svg",
        "ticketpilot-logo-grey.svg",
        "ticketpilot-logo-black.svg",
        "ticketpilot-app-icon-128.png",
        "ticketpilot-app-icon-256.png",
        "ticketpilot-app-icon-512.png",
        "ticketpilot-app-icon-1024.png",
    }


def test_pwa_install_icons_preserve_supplied_source_dimensions() -> None:
    """Home-screen install icons should retain every supplied source size."""

    repository_root = Path(__file__).resolve().parents[1]
    static_icon_dir = repository_root / "ticket_pilot" / "static" / "icons"

    for size in (128, 256, 512, 1024):
        icon_path = static_icon_dir / f"ticketpilot-app-icon-{size}.png"
        assert _png_metadata(icon_path) == (size, size, 16, 6)

    for variant in ("white", "grey", "black"):
        logo_source = (static_icon_dir / f"ticketpilot-logo-{variant}.svg").read_text(encoding="utf-8")
        assert "<svg" in logo_source
        assert 'viewBox="216 179 837 870"' in logo_source
