"""Health check routes for Docker and monitoring."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Return a lightweight liveness response that does not touch secrets."""

    return {"status": "ok"}

