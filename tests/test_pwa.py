"""Regression tests for progressive web app shell metadata."""

from __future__ import annotations

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
    assert 'static/icons/job-logger-icon.svg' in response.text
    assert 'static/icons/job-logger-icon-192.png' in response.text
    assert 'static/pwa.js' in response.text
