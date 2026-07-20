"""Liveness endpoint."""

import os

from fastapi import APIRouter

from src.api.schemas.health import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness probe — returns ok if the process is up, plus the deployed build id."""
    return HealthOut(status="ok", build_id=os.environ.get("BUILD_ID"))
