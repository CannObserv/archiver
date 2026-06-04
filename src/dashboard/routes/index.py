"""Dashboard home — CTA, health strip, Recent Activity, domain overview."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session
from src.core.models import (
    AppUser,
    InfoItem,
    InfoItemSource,
    InfoSource,
    RepSpec,
    SourceRevision,
)
from src.core.models.domain import Domain
from src.dashboard.deps import get_dashboard_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health_partial(
    user: AppUser = Depends(get_dashboard_user),
) -> HTMLResponse:
    """HTMX partial — Archiver health badge."""
    return HTMLResponse('<span class="badge badge--success">ok</span>')


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Dashboard home: CTA, health strip, Recent Activity, domain overview."""
    # Summary counts
    item_count = (await session.execute(select(func.count()).select_from(InfoItem))).scalar_one()
    source_count = (
        await session.execute(select(func.count()).select_from(InfoSource))
    ).scalar_one()
    rep_spec_count = (await session.execute(select(func.count()).select_from(RepSpec))).scalar_one()
    revision_count = (
        await session.execute(select(func.count()).select_from(SourceRevision))
    ).scalar_one()

    # Recent Activity (last 10 revisions)
    recent_revisions = list(
        (
            await session.execute(
                select(SourceRevision).order_by(SourceRevision.captured_at.desc()).limit(10)
            )
        )
        .scalars()
        .all()
    )

    # Batch-load InfoSources for display
    source_ids = list({r.info_source_id for r in recent_revisions})
    sources_by_id: dict = {}
    if source_ids:
        src_rows = list(
            (
                await session.execute(
                    select(InfoSource).where(InfoSource.info_source_id.in_(source_ids))
                )
            )
            .scalars()
            .all()
        )
        sources_by_id = {s.info_source_id: s for s in src_rows}

    # Batch-load active InfoItem for each source (via active InfoItemSource binding)
    items_by_source_id: dict = {}
    if source_ids:
        binding_rows = list(
            (
                await session.execute(
                    select(InfoItemSource).where(
                        InfoItemSource.info_source_id.in_(source_ids),
                        InfoItemSource.deactivated_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        item_ids = list({b.info_item_id for b in binding_rows})
        if item_ids:
            item_rows = list(
                (await session.execute(select(InfoItem).where(InfoItem.info_item_id.in_(item_ids))))
                .scalars()
                .all()
            )
            items_by_id = {i.info_item_id: i for i in item_rows}
            for binding in binding_rows:
                if binding.info_source_id in source_ids:
                    item = items_by_id.get(binding.info_item_id)
                    if item:
                        items_by_source_id[binding.info_source_id] = item

    # Domain overview — top 10 by InfoSource count
    domain_overview = await _get_domain_overview(session)

    watcher_base_url = os.environ.get("WATCHER_BASE_URL", "").strip()
    redis_configured = bool(os.environ.get("ARCHIVER_REDIS_URL", "").strip())

    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "item_count": item_count,
            "source_count": source_count,
            "rep_spec_count": rep_spec_count,
            "revision_count": revision_count,
            "recent_revisions": recent_revisions,
            "sources_by_id": sources_by_id,
            "items_by_source_id": items_by_source_id,
            "domain_overview": domain_overview,
            "watcher_base_url": watcher_base_url or None,
            "redis_configured": redis_configured,
        },
    )


class _DomainRow:
    """Simple data holder for domain overview rows."""

    def __init__(
        self,
        name: str,
        source_count: int,
        item_count: int,
        is_active: bool,
        archived_at,
    ) -> None:
        self.name = name
        self.source_count = source_count
        self.item_count = item_count
        self.is_active = is_active
        self.archived_at = archived_at


async def _get_domain_overview(session: AsyncSession) -> list[_DomainRow]:
    """Return top 10 domains by InfoSource count with item count."""
    # Source counts per domain
    source_counts = (
        await session.execute(
            select(InfoSource.domain_name, func.count().label("cnt"))
            .where(InfoSource.domain_name.is_not(None))
            .group_by(InfoSource.domain_name)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    if not source_counts:
        return []

    domain_names = [row[0] for row in source_counts]

    # Domain rows for status
    domain_rows = {
        d.name: d
        for d in (await session.execute(select(Domain).where(Domain.name.in_(domain_names))))
        .scalars()
        .all()
    }

    # Item counts per domain (via active InfoItemSource → InfoSource)
    item_count_rows = (
        await session.execute(
            select(InfoSource.domain_name, func.count(InfoItemSource.info_item_id).label("cnt"))
            .join(
                InfoItemSource,
                (InfoItemSource.info_source_id == InfoSource.info_source_id)
                & InfoItemSource.deactivated_at.is_(None),
                isouter=True,
            )
            .where(InfoSource.domain_name.in_(domain_names))
            .group_by(InfoSource.domain_name)
        )
    ).all()
    item_counts = {row[0]: row[1] for row in item_count_rows}

    result = []
    for domain_name, src_cnt in source_counts:
        domain = domain_rows.get(domain_name)
        result.append(
            _DomainRow(
                name=domain_name,
                source_count=src_cnt,
                item_count=item_counts.get(domain_name, 0),
                is_active=domain.is_active if domain else True,
                archived_at=domain.archived_at if domain else None,
            )
        )
    return result
