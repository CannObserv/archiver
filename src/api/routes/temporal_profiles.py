"""An InfoItem's temporal profile (archiver#365): ``/info-items/{id}/temporal-profile``.

One profile per item, so a singular resource: ``GET``, a whole-document
``PUT`` (create or replace, never a merge, so no 409), and ``DELETE``. The
service (``src.core.services.temporal_profiles``) evaluates the profile for
today's UTC date, stores the result and announces it on ``info.registry`` when
it moved; the daily boundary job does the rest.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.errors import FieldError, raise_422, raise_envelope
from src.api.schemas.temporal_profile import TemporalProfileOut, TemporalProfilePut
from src.api.schemas.types import ULIDStr
from src.core.models import InfoItem, TemporalProfile
from src.core.services import temporal_profiles as profiles
from src.core.services.temporal_evaluation import utc_today

router = APIRouter(prefix="/info-items", tags=["info-items"])


def _to_out(profile: TemporalProfile) -> TemporalProfileOut:
    return TemporalProfileOut(
        info_item_id=str(profile.info_item_id),
        profile_type=profile.profile_type,
        reference_date=profile.reference_date,
        date_range_start=profile.date_range_start,
        date_range_end=profile.date_range_end,
        rules=profile.rules,
        post_action=profile.post_action,
        is_active=profile.is_active,
        resolved_interval=profile.resolved_interval,
        evaluated_on=profile.evaluated_on,
        fired_at=profile.fired_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def _item_or_404(session: AsyncSession, info_item_id: str) -> None:
    found = (
        await session.execute(
            select(InfoItem.info_item_id).where(InfoItem.info_item_id == info_item_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise_envelope(404, "lookup", "InfoItem not found")


def _profile_missing() -> None:
    raise_envelope(404, "lookup", "TemporalProfile not found")


@router.get("/{info_item_id}/temporal-profile", response_model=TemporalProfileOut)
async def get_temporal_profile(
    info_item_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> TemporalProfileOut:
    """The item's temporal profile; 404 when the item or its profile is missing."""
    await _item_or_404(session, info_item_id)
    profile = await session.get(TemporalProfile, info_item_id)
    if profile is None:
        _profile_missing()
    return _to_out(profile)


@router.put("/{info_item_id}/temporal-profile", response_model=TemporalProfileOut)
async def put_temporal_profile(
    info_item_id: ULIDStr,
    body: TemporalProfilePut,
    session: AsyncSession = Depends(get_db_session),
) -> TemporalProfileOut:
    """Create or replace the item's temporal profile.

    Evaluated for today (UTC) on write: the response's ``resolved_interval`` is
    what the item now announces at the top of its cadence (profile, item,
    domain), and the write announces it when it moved. Every accepted write
    clears ``fired_at``, re-arming the post-action, so a profile whose window
    has already ended is refused with a 422. Stored but not announced on an
    item that cannot announce live (archiver#167).
    """
    fields = body.model_dump()
    fields["rules"] = [rule.model_dump(exclude_none=True) for rule in body.rules]
    try:
        profile = await profiles.put_temporal_profile(
            session, info_item_id, fields, today=utc_today(datetime.now(UTC))
        )
    except profiles.ProfileInvalid as e:
        raise_422(
            "temporal profile failed validation",
            errors=[FieldError(path=path, message=message) for path, message in e.errors],
            source_exc=e,
        )
    if profile is None:
        raise_envelope(404, "lookup", "InfoItem not found")
    await session.commit()
    await session.refresh(profile)
    return _to_out(profile)


@router.delete("/{info_item_id}/temporal-profile", status_code=204)
async def delete_temporal_profile(
    info_item_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Delete the item's temporal profile; the tier below takes over on the wire."""
    await _item_or_404(session, info_item_id)
    if not await profiles.delete_temporal_profile(session, info_item_id):
        _profile_missing()
    await session.commit()
    return Response(status_code=204)
