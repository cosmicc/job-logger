"""Progressive web app metadata routes.

The manifest and service worker are intentionally public, static metadata.
They contain no secrets, no tenant-specific Autotask data, and no user job data.
The service worker is served from the site root so installed mobile app shells
can cover the normal authenticated routes without widening data access.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["pwa"])

STATIC_DIRECTORY = Path(__file__).resolve().parent.parent / "static"
"""Filesystem path for source-controlled static PWA assets."""


@router.get("/manifest.webmanifest", include_in_schema=False)
def web_app_manifest() -> FileResponse:
    """Return install metadata used by mobile browsers and home-screen launchers."""

    return FileResponse(
        STATIC_DIRECTORY / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    """Return the root-scoped service worker without caching authenticated pages."""

    return FileResponse(
        STATIC_DIRECTORY / "service-worker.js",
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Service-Worker-Allowed": "/",
        },
    )
