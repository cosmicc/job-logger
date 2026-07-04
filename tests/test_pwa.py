"""Regression tests for progressive web app shell metadata."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
APP_DARK_ICON_BACKGROUND = (11, 18, 32, 255)


def _first_png_pixel_rgba(image_path: Path) -> tuple[int, int, int, int]:
    """Return the first RGBA pixel from a non-interlaced 8-bit PNG asset."""

    png_bytes = image_path.read_bytes()
    assert png_bytes.startswith(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    width = 0
    color_type = 0
    idat_chunks: list[bytes] = []
    while offset < len(png_bytes):
        chunk_length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_data = png_bytes[offset + 8 : offset + 8 + chunk_length]
        offset += 12 + chunk_length
        if chunk_type == b"IHDR":
            width, _height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk_data)
            assert bit_depth == 8
            assert color_type == 6
            assert interlace == 0
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    raw_pixels = zlib.decompress(b"".join(idat_chunks))
    bytes_per_pixel = 4
    row_length = width * bytes_per_pixel
    filter_type = raw_pixels[0]
    scanline = bytearray(raw_pixels[1 : 1 + row_length])
    if filter_type == 1:
        for index in range(bytes_per_pixel, row_length):
            scanline[index] = (scanline[index] + scanline[index - bytes_per_pixel]) & 0xFF
    elif filter_type == 2:
        pass
    elif filter_type == 3:
        for index in range(bytes_per_pixel, row_length):
            scanline[index] = (scanline[index] + (scanline[index - bytes_per_pixel] // 2)) & 0xFF
    elif filter_type == 4:
        for index in range(bytes_per_pixel, row_length):
            left = scanline[index - bytes_per_pixel]
            scanline[index] = (scanline[index] + left) & 0xFF
    else:
        assert filter_type == 0

    return tuple(scanline[:4])


def test_manifest_exposes_standalone_mobile_app_metadata(client: TestClient) -> None:
    """The web app manifest should make the mobile workflow installable."""

    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "Job Logger"
    assert manifest["start_url"] == "/home"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0b1220"
    icon_sources = {icon["src"] for icon in manifest["icons"]}
    assert "/static/icons/job-logger-install-icon.svg" in icon_sources
    assert "/static/icons/job-logger-install-icon-192.png" in icon_sources
    assert "/static/icons/job-logger-install-icon-512.png" in icon_sources
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
    assert 'static/icons/job-logger-install-icon.svg?v=' in response.text
    assert 'static/icons/job-logger-install-icon-192.png?v=' in response.text
    assert 'static/pwa.js' in response.text


def test_logo_design_assets_are_source_controlled() -> None:
    """Logo source files and SVG wrappers should stay available for design reference."""

    repository_root = Path(__file__).resolve().parents[1]
    design_dir = repository_root / "docs" / "design"
    expected_assets = (
        "job_logger_icon.png",
        "job_logger_icon.svg",
        "job_logger_transparent.png",
        "job_logger_transparent.svg",
        "job_logger_fully_transparent.png",
        "job_logger_fully_transparent.svg",
        "color_palette.png",
    )

    for asset_name in expected_assets:
        assert (design_dir / asset_name).is_file()

    static_icon_dir = repository_root / "job_logger" / "static" / "icons"
    assert (static_icon_dir / "job-logger-logo-transparent.png").is_file()
    assert (static_icon_dir / "job-logger-logo-fully-transparent.png").is_file()


def test_pwa_install_icons_use_full_frame_icon_format_artwork() -> None:
    """Home-screen install icons should use the full-frame icon-format artwork."""

    repository_root = Path(__file__).resolve().parents[1]
    static_icon_dir = repository_root / "job_logger" / "static" / "icons"

    icon_svg = (static_icon_dir / "job-logger-install-icon.svg").read_text(encoding="utf-8")

    assert (static_icon_dir / "job-logger-install-icon-192.png").is_file()
    assert (static_icon_dir / "job-logger-install-icon-512.png").is_file()
    assert _first_png_pixel_rgba(static_icon_dir / "job-logger-install-icon-192.png") == APP_DARK_ICON_BACKGROUND
    assert _first_png_pixel_rgba(static_icon_dir / "job-logger-install-icon-512.png") == APP_DARK_ICON_BACKGROUND
    assert "Job Logger icon-format install icon" in icon_svg
    assert (
        "Full-size PWA install icon generated from the original dark-background "
        "Job Logger icon artwork."
    ) in icon_svg
