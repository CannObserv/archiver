"""InfoSpec CRUD endpoints (nested under InfoItem).

NOTE: These routes are temporarily disabled in B9 because the InfoSpec ORM
model was removed in the v2 restructure. B11 will delete this file entirely
and replace with v2 source/rep-spec management endpoints.
"""

# ruff: noqa: ERA001

from fastapi import APIRouter

router = APIRouter(prefix="/info-items/{info_item_id}", tags=["info-specs"])

# ---------------------------------------------------------------------------
# Legacy routes commented out — InfoSpec ORM removed in v2 (B9).
# B11 deletes this file and replaces with v2 endpoints.
# ---------------------------------------------------------------------------

# from fastapi import Depends, HTTPException
# from sqlalchemy import func, select
# from sqlalchemy.ext.asyncio import AsyncSession
#
# from src.api.deps import get_db_session
# from src.api.schemas.info_spec import (
#     InfoSpecCreate,
#     InfoSpecOut,
#     InfoSpecPatch,
# )
# from src.api.schemas.types import ULIDStr
# from src.api.serializers import info_spec_to_out
# from src.core.info_spec_schema import (
#     InfoSpecValidationError,
#     validate_info_spec,
# )
# from src.core.models import InfoItem, InfoSpec
#
# async def _ensure_item_exists(session, info_item_id):
#     ...
#
# @router.post("/info-specs", ...)
# async def create_info_spec(...):
#     ...
#
# @router.get("/info-specs", ...)
# async def list_info_specs(...):
#     ...
#
# @router.get("/primary-info-spec", ...)
# async def get_primary_info_spec(...):
#     ...
#
# @router.patch("/info-specs/{info_spec_id}", ...)
# async def patch_info_spec(...):
#     ...
