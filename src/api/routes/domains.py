"""Top-level Domain endpoints.

Domains are upserted via PATCH (create-or-update). DELETE is guarded — a
domain that has InfoSources referencing it cannot be deleted (409).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.errors import raise_envelope
from src.api.schemas.domain import DomainOut, DomainPatch
from src.api.schemas.pagination import Page
from src.core.models import InfoSource
from src.core.models.domain import Domain

router = APIRouter(prefix="/domains", tags=["domains"])


def _domain_to_out(d: Domain) -> DomainOut:
    return DomainOut(
        id=str(d.id),
        name=d.name,
        notes=d.notes,
        is_active=d.is_active,
        archived_at=d.archived_at,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.get("", response_model=Page[DomainOut])
async def list_domains(
    is_active: bool | None = Query(default=None, description="Filter by active status."),
    archived: bool | None = Query(
        default=None, description="When true, return only archived domains."
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> Page[DomainOut]:
    """List domains with offset pagination."""
    stmt = select(Domain).order_by(Domain.created_at, Domain.id)
    if is_active is not None:
        stmt = stmt.where(Domain.is_active == is_active)
    if archived is True:
        stmt = stmt.where(Domain.archived_at.is_not(None))
    elif archived is False:
        stmt = stmt.where(Domain.archived_at.is_(None))
    stmt = stmt.offset(offset).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    return Page[DomainOut](
        items=[_domain_to_out(d) for d in rows[:limit]],
        has_more=has_more,
        limit=limit,
        offset=offset,
    )


@router.get("/{name}", response_model=DomainOut)
async def get_domain(
    name: str,
    session: AsyncSession = Depends(get_db_session),
) -> DomainOut:
    """Fetch a single Domain by hostname."""
    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")
    return _domain_to_out(domain)


@router.patch("/{name}", response_model=DomainOut)
async def upsert_domain(
    name: str,
    body: DomainPatch,
    session: AsyncSession = Depends(get_db_session),
) -> DomainOut:
    """Upsert a Domain by hostname.

    Creates on first call. Updates notes and/or is_active on subsequent calls.
    """
    now = datetime.now(UTC)
    insert_values: dict = {"name": name, "updated_at": now}
    if body.notes is not None:
        insert_values["notes"] = body.notes
    if body.is_active is not None:
        insert_values["is_active"] = body.is_active

    update_values: dict = {"updated_at": now}
    if body.notes is not None:
        update_values["notes"] = body.notes
    if body.is_active is not None:
        update_values["is_active"] = body.is_active

    stmt = (
        pg_insert(Domain)
        .values(**insert_values)
        .on_conflict_do_update(index_elements=["name"], set_=update_values)
    )
    await session.execute(stmt)

    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one()
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)


@router.delete("/{name}", status_code=204)
async def delete_domain(
    name: str,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a Domain. Returns 409 if InfoSources reference it."""
    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")

    count = (
        await session.execute(
            select(func.count()).select_from(InfoSource).where(InfoSource.domain_name == name)
        )
    ).scalar_one()
    if count > 0:
        raise_envelope(
            409,
            "conflict",
            f"Domain has {count} InfoSource(s) referencing it; deactivate them first.",
        )

    await session.delete(domain)
    await session.commit()


@router.post("/{name}/archive", response_model=DomainOut)
async def archive_domain(
    name: str,
    session: AsyncSession = Depends(get_db_session),
) -> DomainOut:
    """Set archived_at on a Domain."""
    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")

    domain.archived_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)


@router.post("/{name}/restore", response_model=DomainOut)
async def restore_domain(
    name: str,
    session: AsyncSession = Depends(get_db_session),
) -> DomainOut:
    """Clear archived_at on a Domain."""
    result = await session.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")

    domain.archived_at = None
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)
