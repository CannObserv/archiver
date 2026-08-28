"""Dashboard home - CTA, health strip, Recent Activity, domain overview."""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS, CONTENT_REVISIONS
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_db_session, get_redis_client
from src.core.bus_health import GroupLag, collect_group_lag
from src.core.changes.group_consumer import consumer_enabled
from src.core.changes.outbox_stats import BACKLOG_WARN_AGE_SECONDS, collect_outbox_stats
from src.core.logging import get_logger
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

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisAsync

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health_partial(
    user: AppUser = Depends(get_dashboard_user),
) -> HTMLResponse:
    """HTMX partial - Archiver health badge."""
    return HTMLResponse('<span class="badge badge--success">ok</span>')


@router.get("/health/redis", response_class=HTMLResponse)
async def dashboard_health_redis(
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> HTMLResponse:
    """HTMX partial - Redis health badge."""
    if redis is None:
        return HTMLResponse('<span class="badge badge--muted">not configured</span>')
    try:
        await redis.ping()
        return HTMLResponse('<span class="badge badge--success">ok</span>')
    except Exception as exc:
        reason = str(exc)
        logger.warning("Redis health check failed", extra={"error": reason})
        return HTMLResponse(
            f'<span class="badge badge--danger" title="{html_escape(reason)}">error</span>'
        )


@router.get("/health/outbox", response_class=HTMLResponse)
async def dashboard_health_outbox(
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> HTMLResponse:
    """HTMX partial - outbox publisher health badge (archiver#112).

    muted "not draining": no Redis client, so the publisher is not running -
    rows cannot drain and a stale backlog is the configured-off state, not ill
    health (the dev server is bus-dormant by design; CR round 1, finding 1).
    danger: any dead-lettered (poison) row - needs an operator.
    warning: oldest live unpublished row older than the backlog threshold -
    the drain is not keeping up or Redis has been down a while.
    success otherwise; the title carries the raw numbers in every drain state.
    """
    if redis is None:
        return HTMLResponse('<span class="badge badge--muted">not draining</span>')
    try:
        stats = await collect_outbox_stats(session)
    except Exception as exc:
        reason = str(exc)
        logger.warning("Outbox health check failed", extra={"error": reason})
        return HTMLResponse(
            f'<span class="badge badge--danger" title="{html_escape(reason)}">error</span>'
        )

    age = stats.oldest_unpublished_age_seconds
    parts = [f"depth={stats.unpublished_count}"]
    if age is not None:
        parts.append(f"oldest={int(age)}s")
    parts.append(f"dead_lettered={stats.dead_lettered_count}")
    detail = html_escape(" ".join(parts))
    if stats.dead_lettered_count:
        return HTMLResponse(
            f'<span class="badge badge--danger" title="{detail}">'
            f"{stats.dead_lettered_count} dead-lettered</span>"
        )
    if age is not None and age > BACKLOG_WARN_AGE_SECONDS:
        return HTMLResponse(f'<span class="badge badge--warning" title="{detail}">backlog</span>')
    return HTMLResponse(f'<span class="badge badge--success" title="{detail}">ok</span>')


# Each archiver-owned consumer, paired with the ``app.state`` handle its
# lifespan branch sets and the topic its group reads. Both are gated by the
# same ARCHIVER_BUS_CONSUMER, so one badge answers for both - and a badge blind
# to half the consumers would reproduce the misleading green #147 closes.
_CONSUMERS: tuple[tuple[str, str, str], ...] = (
    ("revisions", "revisions_consumer_task", CONTENT_REVISIONS),
    ("artifacts", "artifacts_consumer_task", CONTENT_ARTIFACTS),
)


def _badge(variant: str, text: str, *, detail: str = "") -> HTMLResponse:
    """One badge span. ``detail`` must already be HTML-escaped."""
    title = f' title="{detail}"' if detail else ""
    return HTMLResponse(f'<span class="badge badge--{variant}"{title}>{text}</span>')


def _task_state(task: "asyncio.Task | None") -> str:
    """Liveness of one consumer task, straight off ``app.state``.

    No broker round-trip: the handle is already there, and it is the only
    signal that separates "gated on and healthy" from "gated on and dead" -
    the pair an environment variable cannot tell apart (archiver#147).
    """
    if task is None:
        return "not started"
    if not task.done():
        return "running"
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        # Task.exception() *raises* on a cancelled task rather than returning.
        # Shutdown cancels these, so this is a normal path, not an error one.
        return "stopped (cancelled)"
    return f"stopped ({exc!r})" if exc is not None else "stopped (clean exit)"


@router.get("/health/consumers", response_class=HTMLResponse)
async def dashboard_health_consumers(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> HTMLResponse:
    """HTMX partial - bus consumer liveness and group lag (archiver#147).

    Replaces a single ``ARCHIVER_REDIS_URL`` boolean that rendered green over
    three different states: gated off, gated on with a dead loop, and healthy.
    The middle one is the one that silently loses ground - revisions stop being
    recorded while ``content.revisions`` keeps growing - so it gets its own
    badge state here rather than sharing the healthy one.

    Liveness comes from ``app.state`` (no broker call); the depths come from
    ``src.core.bus_health``, the same probe module the #130 timer uses, so the
    dashboard and journald never disagree about what a lagging group is.
    """
    if redis is None:
        return _badge("muted", "not configured")
    if not consumer_enabled(os.environ.get("ARCHIVER_BUS_CONSUMER")):
        # The one state that *is* configuration, reported as configuration: the
        # gate is what makes the dev server bus-dormant by design, so off is
        # muted, not a warning. Everything below this line is measured.
        return _badge("muted", "gated off")

    states = {
        name: _task_state(getattr(request.app.state, attr, None))
        for name, attr, _topic in _CONSUMERS
    }

    lags: dict[str, GroupLag] = {}
    lag_error: str | None = None
    try:
        lags = {lag.topic: lag for lag in await collect_group_lag(redis)}
    except Exception as exc:
        lag_error = str(exc) or repr(exc)
        logger.warning("Consumer lag probe failed", extra={"error": lag_error})

    parts = []
    for name, _attr, topic in _CONSUMERS:
        lag = lags.get(topic)
        if lag is None:
            parts.append(f"{name}={states[name]} pending=? dlq=?")
        else:
            pending = "group missing" if lag.pending is None else lag.pending
            parts.append(f"{name}={states[name]} pending={pending} dlq={lag.dlq_depth}")
    if lag_error:
        parts.append(f"lag probe failed: {lag_error}")
    detail = html_escape("; ".join(parts))

    # Liveness first: a stopped consumer is the cause, and any lag reading is
    # its symptom. Ordering the other way would report the symptom and bury
    # the thing an operator has to act on.
    if any(state == "not started" for state in states.values()):
        return _badge("danger", "not started", detail=detail)
    if any(state.startswith("stopped") for state in states.values()):
        return _badge("danger", "stopped", detail=detail)
    if lag_error:
        # The consumers are demonstrably alive, but the depths are unknown -
        # which must not render as measured zeroes. The Redis badge alongside
        # carries the broker's own reachability.
        return _badge("warning", "lag unknown", detail=detail)

    dead_lettered = sum(lag.dlq_depth for lag in lags.values())
    if dead_lettered:
        # Actionable even while both consumers run normally: every entry is a
        # frame the registry decided it could never use (archiver#162).
        return _badge("danger", f"{dead_lettered} dead-lettered", detail=detail)
    if any(lag.pending is None for lag in lags.values()):
        return _badge("warning", "group missing", detail=detail)
    if any(lag.pending for lag in lags.values()):
        # Raw depth, not the timer's two-tick rule: that debounces a periodic
        # alarm, where a dashboard shows one instant and the operator refreshes.
        return _badge("warning", "lagging", detail=detail)
    return _badge("success", "running", detail=detail)


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

    # Domain overview - top 10 by InfoSource count
    domain_overview = await _get_domain_overview(session)

    # No `redis_configured` flag: the strip used to branch on ARCHIVER_REDIS_URL
    # to decide whether to render a live badge or a static "not configured" one,
    # which is reporting configuration as if it were state (archiver#147). Every
    # badge is a live route now, and "not configured" is that route's answer.
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
        },
    )


@dataclass
class _DomainRow:
    name: str
    source_count: int
    item_count: int
    is_active: bool
    archived_at: datetime | None


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
