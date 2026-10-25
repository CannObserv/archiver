"""Top-level Domain endpoints.

Domains are upserted via PATCH (create-or-update). DELETE is guarded — a
domain that has InfoSources referencing it cannot be deleted (409).

PATCH, archive and restore go through ``update_domain``: each can suspend or
resume the host, which re-announces its items on ``info.registry`` in the same
transaction (archiver#360).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.api.errors import FieldError, raise_422, raise_envelope
from src.api.schemas.domain import DomainOut, DomainPatch
from src.api.schemas.pagination import Page
from src.core.models import InfoSource
from src.core.models.domain import Domain
from src.core.services.domain_policy import update_domain
from src.core.url_canonicalization import is_canonical_hostname, source_hostname
from src.core.watch_spec_schema.validator import validate_domain_watch_spec

router = APIRouter(prefix="/domains", tags=["domains"])


def _domain_to_out(d: Domain) -> DomainOut:
    return DomainOut(
        id=str(d.id),
        name=d.name,
        notes=d.notes,
        is_active=d.is_active,
        archived_at=d.archived_at,
        min_interval_seconds=d.min_interval_seconds,
        default_watch_spec=d.default_watch_spec,
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
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
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

    Creates on first call. Updates only the fields sent; ``default_watch_spec:
    null`` clears the cadence. ``name`` must be a canonical host name - the
    lowercase, port-less form an InfoSource is filed under - or it is a 422.
    A change to ``is_active`` that suspends or resumes the host announces its
    items (archiver#360).
    """
    if not is_canonical_hostname(name):
        _refuse_non_canonical(name)
    changes: dict = {"updated_at": datetime.now(UTC)}
    if body.notes is not None:
        changes["notes"] = body.notes
    if body.is_active is not None:
        changes["is_active"] = body.is_active
    if "min_interval_seconds" in body.model_fields_set:
        changes["min_interval_seconds"] = body.min_interval_seconds
    if "default_watch_spec" in body.model_fields_set:
        if body.default_watch_spec is not None:
            _check_default_watch_spec(body.default_watch_spec)
        changes["default_watch_spec"] = body.default_watch_spec

    domain = await update_domain(session, name, changes, create=True)
    if domain is None:  # a DELETE landed between the upsert's insert and its lock (CR 15)
        raise_envelope(409, "conflict", "Domain was deleted concurrently; retry the upsert.")
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)


def _refuse_non_canonical(name: str) -> None:
    """422 for a name no InfoSource could be filed under (CR 22).

    Such a row would match no source, so suspending it would suppress nothing
    while reading as done. The message names the spelling a source would carry.
    """
    try:
        hint = source_hostname(f"https://{name}/")
    except ValueError:
        hint = None
    suggestion = f"; did you mean {hint!r}?" if hint and hint != name else ""
    raise_422(
        f"{name!r} is not a canonical host name (lowercase, no port or path){suggestion}",
        kind="domain",
        errors=[FieldError(path="/name", message="not a canonical host name")],
    )


def _check_default_watch_spec(doc: dict) -> None:
    """422 unless ``doc`` is a WatchSpec v1 document carrying ``interval``."""
    ok, errors = validate_domain_watch_spec(doc)
    if not ok:
        raise_422(
            "default_watch_spec failed validation (send null for no domain default)",
            errors=[FieldError(path=e["path"], message=e["message"]) for e in errors],
        )


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
    """Set archived_at on a Domain; suspends the host (archiver#360)."""
    domain = await update_domain(session, name, {"archived_at": datetime.now(UTC)}, create=False)
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)


@router.post("/{name}/restore", response_model=DomainOut)
async def restore_domain(
    name: str,
    session: AsyncSession = Depends(get_db_session),
) -> DomainOut:
    """Clear archived_at on a Domain; resumes the host unless it is inactive."""
    domain = await update_domain(session, name, {"archived_at": None}, create=False)
    if domain is None:
        raise_envelope(404, "lookup", "Domain not found")
    await session.commit()
    await session.refresh(domain)
    return _domain_to_out(domain)
