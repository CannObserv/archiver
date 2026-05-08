"""InfoItem CRUD endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.schemas.info_item import (
    InfoItemCreate,
    InfoItemOut,
)
from src.api.schemas.types import ULIDStr
from src.api.serializers import info_item_to_out
from src.core.models import InfoItem, InfoItemRepSpec, InfoItemSource, InfoSource, RepSpec
from src.core.rep_fields_schema.validator import validate_rep_fields_against_spec
from src.core.source_spec_schema.validator import validate_root_source_spec
from src.core.url_canonicalization import canonicalize_url

router = APIRouter(prefix="/info-items", tags=["info-items"])


@router.post("", response_model=InfoItemOut, status_code=201)
async def create_info_item(
    body: InfoItemCreate, session: AsyncSession = Depends(get_db_session)
) -> InfoItemOut:
    """Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.
    """
    # --- 1. Validate initial_source_spec ---
    if body.initial_source_spec is not None:
        ok, errors = validate_root_source_spec(body.initial_source_spec)
        if not ok:
            raise HTTPException(
                status_code=422,
                detail={"message": "invalid source_spec", "errors": errors},
            )

    # --- 2. Look up RepSpecs + validate rep_fields against required_fields ---
    rep_spec_rows: list[RepSpec] = []
    for assignment in body.initial_rep_spec_assignments:
        result = await session.execute(
            select(RepSpec).where(RepSpec.rep_spec_id == assignment.rep_spec_id)
        )
        rep_spec = result.scalar_one_or_none()
        if rep_spec is None:
            raise HTTPException(
                status_code=404,
                detail=f"RepSpec {assignment.rep_spec_id!r} not found",
            )
        rep_spec_rows.append(rep_spec)

        required_fields: list[str] = rep_spec.document.get("required_fields", [])
        if required_fields:
            ok, errors = validate_rep_fields_against_spec(body.rep_fields, required_fields)
            if not ok:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": (
                            f"rep_fields does not satisfy RepSpec {assignment.rep_spec_id!r}"
                        ),
                        "errors": errors,
                    },
                )

    # --- 3. Insert InfoItem ---
    item = InfoItem(
        name=body.name,
        description=body.description,
        owner=body.owner,
        rep_fields=body.rep_fields,
    )
    session.add(item)
    await session.flush()  # populate item.info_item_id

    # --- 4. Insert InfoSource + InfoItemSource ---
    new_sources: list[InfoItemSource] = []
    if body.initial_source_spec is not None:
        source_spec_doc: dict = dict(body.initial_source_spec)

        # Canonicalize target.url before storing
        raw_url: str | None = source_spec_doc.get("target", {}).get("url")
        if raw_url:
            strip_keys: list[str] = (
                source_spec_doc.get("target", {})
                .get("url_canonicalization", {})
                .get("strip_query_keys", [])
            )
            canonical = canonicalize_url(raw_url, strip_query_keys=strip_keys or None)
            source_spec_doc["target"] = dict(source_spec_doc["target"])
            source_spec_doc["target"]["url"] = canonical

        info_source = InfoSource(
            source_spec=source_spec_doc,
            schema_version=source_spec_doc.get("schema_version", 1),
        )
        session.add(info_source)
        await session.flush()  # populate info_source.info_source_id

        binding = InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=info_source.info_source_id,
            role="primary",
        )
        session.add(binding)
        await session.flush()
        new_sources.append(binding)

    # --- 5. Insert InfoItemRepSpec rows ---
    new_rep_specs: list[InfoItemRepSpec] = []
    for assignment, rep_spec in zip(body.initial_rep_spec_assignments, rep_spec_rows):
        activated_at = assignment.activated_at or datetime.now(UTC)
        airs = InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=rep_spec.rep_spec_id,
            activated_at=activated_at,
        )
        session.add(airs)
        new_rep_specs.append(airs)

    await session.flush()
    await session.commit()
    await session.refresh(item)

    return info_item_to_out(item, sources=new_sources, rep_specs=new_rep_specs)


@router.get("", response_model=list[InfoItemOut])
async def list_info_items(
    session: AsyncSession = Depends(get_db_session),
) -> list[InfoItemOut]:
    """List all InfoItems (no related rows populated)."""
    result = await session.execute(select(InfoItem).order_by(InfoItem.created_at))
    return [info_item_to_out(item) for item in result.scalars().all()]


@router.get("/{info_item_id}", response_model=InfoItemOut)
async def get_info_item(
    info_item_id: ULIDStr, session: AsyncSession = Depends(get_db_session)
) -> InfoItemOut:
    """Fetch a single InfoItem by ID (no related rows populated)."""
    result = await session.execute(select(InfoItem).where(InfoItem.info_item_id == info_item_id))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="InfoItem not found")
    return info_item_to_out(item)
