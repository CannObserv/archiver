"""Top-level InfoSource endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api.deps import get_db_session, get_watcher_client, require_api_key
from src.api.errors import raise_422, raise_envelope
from src.api.schemas.info_source import InfoSourceCreate, InfoSourceOut, InfoSourcePatch
from src.api.schemas.pagination import Page
from src.api.schemas.types import ULIDStr
from src.api.serializers import info_source_to_out
from src.core.models import InfoSource
from src.core.services.registry_announcement import announce_for_info_source
from src.core.tools.create_info_source import (
    CreateInfoSourceError,
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)
from src.core.tools.update_info_source_specs import (
    InfoSourceNotFoundError as UpdateNotFoundError,
)
from src.core.tools.update_info_source_specs import (
    InvalidSourceSpecError as UpdateInvalidSpecError,
)
from src.core.tools.update_info_source_specs import (
    MixedAlgorithmFamilyError as UpdateMixedFamilyError,
)
from src.core.tools.update_info_source_specs import update_info_source_specs
from src.core.watcher_provisioning import sync_on_spec_update

if TYPE_CHECKING:
    from watcher_client import WatcherClient

router = APIRouter(prefix="/info-sources", tags=["info-sources"])


@router.post("", response_model=InfoSourceOut, status_code=201)
async def create_info_source_route(
    body: InfoSourceCreate,
    session: AsyncSession = Depends(get_db_session),
    _key=Depends(require_api_key),
) -> InfoSourceOut:
    """Create a new InfoSource.

    Multiple InfoSources with the same URL are valid — different InfoItems may
    extract distinct semantic content from the same URL using different specs.
    """
    try:
        src = await create_info_source(session, url=body.url, source_specs=body.source_specs)
    except InvalidUrlError as e:
        raise_422("invalid url", kind="domain", source_exc=e)
    except InvalidSourceSpecError as e:
        raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)
    except MixedAlgorithmFamilyError as e:
        raise_422("mixed algorithm families in source_specs", kind="domain", source_exc=e)
    except CreateInfoSourceError as e:
        raise_422(str(e), kind="domain", source_exc=e)

    await session.commit()
    await session.refresh(src)
    return info_source_to_out(src)


@router.patch("/{info_source_id}/source-specs", response_model=InfoSourceOut)
async def patch_info_source_specs(
    info_source_id: ULIDStr,
    body: InfoSourcePatch,
    session: AsyncSession = Depends(get_db_session),
    _key=Depends(require_api_key),
    watcher: WatcherClient | None = Depends(get_watcher_client),
) -> InfoSourceOut:
    """Replace the source_specs list on an existing InfoSource.

    URL is immutable; only source_specs may be updated.
    """
    try:
        src = await update_info_source_specs(
            session,
            info_source_id=ULID.from_str(info_source_id),
            source_specs=body.source_specs,
        )
    except UpdateNotFoundError as e:
        raise_envelope(404, "lookup", "InfoSource not found", source_exc=e)
    except UpdateInvalidSpecError as e:
        raise_422("invalid source_spec", kind="schema", errors=e.errors, source_exc=e)
    except UpdateMixedFamilyError as e:
        raise_422("mixed algorithm families in source_specs", kind="domain", source_exc=e)

    # Fan out: one InfoSource can be the active primary for several InfoItems,
    # and the announcement grain is the item — N bindings, N announcements.
    await announce_for_info_source(session, ULID.from_str(info_source_id))
    await session.commit()
    await session.refresh(src)

    await sync_on_spec_update(session, watcher, ULID.from_str(info_source_id), body.source_specs)

    return info_source_to_out(src)


@router.get("", response_model=Page[InfoSourceOut])
async def list_info_sources(
    url: str | None = Query(default=None, description="Filter by exact URL."),
    domain_name: str | None = Query(default=None, description="Filter by domain hostname."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
    session: AsyncSession = Depends(get_db_session),
    _key=Depends(require_api_key),
) -> Page[InfoSourceOut]:
    """List InfoSources with offset pagination, optionally filtered by URL or domain."""
    stmt = select(InfoSource).order_by(InfoSource.created_at, InfoSource.info_source_id)
    if url is not None:
        stmt = stmt.where(InfoSource.url == url)
    if domain_name is not None:
        stmt = stmt.where(InfoSource.domain_name == domain_name)
    stmt = stmt.offset(offset).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[InfoSourceOut](
        items=[info_source_to_out(s) for s in rows],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/{info_source_id}", response_model=InfoSourceOut)
async def get_info_source(
    info_source_id: ULIDStr,
    session: AsyncSession = Depends(get_db_session),
    _key=Depends(require_api_key),
) -> InfoSourceOut:
    """Fetch a single InfoSource by ID."""
    src = await session.get(InfoSource, ULID.from_str(info_source_id))
    if src is None:
        raise_envelope(404, "lookup", "InfoSource not found")
    return info_source_to_out(src)
