"""Regression tests for progressive web app shell metadata."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


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
    assert any(icon["src"].endswith("job-logger-icon-192.png") for icon in manifest["icons"])
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])


def test_service_worker_is_root_scoped_and_does_not_cache_workflow_data(client: TestClient) -> None:
    """The PWA worker should support install behavior without storing private pages."""

    response = client.get("/service-worker.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["service-worker-allowed"] == "/"
    assert "caches.open" not in response.text
    assert "fetch(event.request)" in response.text


def test_base_template_registers_pwa_assets(client: TestClient) -> None:
    """Rendered pages should advertise install metadata and register the worker."""

    response = client.get("/login")

    assert response.status_code == 200
    assert '<link rel="manifest" href="/manifest.webmanifest">' in response.text
    assert 'name="mobile-web-app-capable" content="yes"' in response.text
    assert 'name="apple-mobile-web-app-capable" content="yes"' in response.text
    assert 'name="apple-mobile-web-app-status-bar-style" content="black-translucent"' in response.text
    assert 'static/icons/job-logger-icon.svg?v=' in response.text
    assert 'static/icons/job-logger-icon-192.png?v=' in response.text
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


def test_pwa_install_icons_use_padded_transparent_logo_asset() -> None:
    """Home-screen install icons should use the padded semi-transparent logo."""

    repository_root = Path(__file__).resolve().parents[1]
    static_icon_dir = repository_root / "job_logger" / "static" / "icons"

    icon_svg = (static_icon_dir / "job-logger-icon.svg").read_text(encoding="utf-8")
    maskable_svg = (static_icon_dir / "job-logger-icon-maskable.svg").read_text(encoding="utf-8")

    assert "Job Logger semi-transparent install icon" in icon_svg
    assert "Padded any-purpose PWA icon generated from the semi-transparent Job Logger logo." in icon_svg
    assert "Padded maskable PWA icon generated from the semi-transparent Job Logger logo." in maskable_svg
