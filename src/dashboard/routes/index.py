"""Dashboard home - CTA, health strip, Recent Activity, domain overview."""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import partial
from html import escape as html_escape
from pathlib import Path
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS, CONTENT_REVISIONS
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
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
from src.core.tools.audit_stored_documents import audit_stored_documents
from src.dashboard.deps import get_dashboard_user
from src.dashboard.stored_documents import finding_views

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisAsync

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Well under any sane HTMX badge wait. A tick that cannot answer inside it
# has nothing useful to report, and the operator gets "lag unknown" plus a
# live Redis badge beside it rather than a spinner that never resolves.
LAG_PROBE_TIMEOUT_SECONDS = 5.0


@router.get("/health", response_class=HTMLResponse)
async def dashboard_health_partial(
    user: AppUser = Depends(get_dashboard_user),
) -> HTMLResponse:
    """HTMX partial - Archiver health badge."""
    return HTMLResponse('<span class="badge badge--success">ok</span>')


# Where the Outbox and Consumers badges link, in every state (archiver#271): the
# screen that triages what they report. Linked whatever the badge reads, so the
# screen is reachable from the dashboard while there is nothing to triage too -
# and while the bus is dormant or broken, when its outbox section still works.
BUS_TRIAGE_HREF = "/dashboard/bus-triage"


def _badge(variant: str, text: str, *, detail: str = "", triage_for: str = "") -> HTMLResponse:
    """One badge. ``detail`` must already be HTML-escaped.

    ``triage_for`` is the health-row label of a badge that links to the Bus triage
    screen ("Outbox", "Consumers"). The link's accessible name carries it, because
    a link read out of context as just "ok" says nothing about where it goes.
    """
    title = f' title="{detail}"' if detail else ""
    if triage_for:
        label = html_escape(f"{triage_for}: {text} - open Bus triage")
        return HTMLResponse(
            f'<a href="{BUS_TRIAGE_HREF}" class="badge badge--{variant}" '
            f'aria-label="{label}"{title}>{text}</a>'
        )
    return HTMLResponse(f'<span class="badge badge--{variant}"{title}>{text}</span>')


INIT_FAILED_DETAIL = (
    "ARCHIVER_REDIS_URL is set but no client exists - bus init raised "
    "at startup; see the lifespan's logged exception"
)


def bus_init_failed() -> bool:
    """With no Redis client, whether that is init failure rather than dormancy.

    The lifespan nulls the client both when ``ARCHIVER_REDIS_URL`` is unset and
    when init raised with it set; only the URL tells them apart. One reading,
    shared by the badges and the Bus triage screen (archiver#271), so the two
    cannot disagree about which state the bus is in.
    """
    return bool(os.environ.get("ARCHIVER_REDIS_URL", "").strip())


def _no_client_badge(*, triage_for: str = "") -> HTMLResponse:
    """The badge for ``app.state.redis_client is None``, split by *why*.

    The lifespan nulls the client both when ``ARCHIVER_REDIS_URL`` is unset (the
    dev server's bus-dormant default) and when publisher init *raised* with the
    URL set (``src/api/main.py``). Rendering the second as "not configured" is
    the configuration-as-state conflation archiver#147 exists to remove,
    surviving in a rarer branch - a broken production bus wearing the dev
    server's vocabulary. The URL is read here as configuration, which is all it
    is asked to answer (CR round 1, finding 3). Shared by the Redis badge, which
    never links, and the Consumers badge, which passes ``triage_for``.
    """
    if bus_init_failed():
        return _badge(
            "danger",
            "init failed",
            detail=html_escape(INIT_FAILED_DETAIL),
            triage_for=triage_for,
        )
    return _badge("muted", "not configured", triage_for=triage_for)


@router.get("/health/redis", response_class=HTMLResponse)
async def dashboard_health_redis(
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
) -> HTMLResponse:
    """HTMX partial - Redis health badge."""
    if redis is None:
        return _no_client_badge()
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

    muted "not draining": no Redis client *and* no ARCHIVER_REDIS_URL, so the
    publisher is not running - rows cannot drain and a stale backlog is the
    configured-off state, not ill health (the dev server is bus-dormant by
    design; #112 CR round 1, finding 1). danger "not draining (init failed)"
    when the URL *is* set: bus init raised, which is exactly when a stale
    backlog is ill health rather than dormancy (#147 CR round 2, finding 10).
    danger: any dead-lettered (poison) row - needs an operator.
    warning: oldest live unpublished row older than the backlog threshold -
    the drain is not keeping up or Redis has been down a while.
    success otherwise; the title carries the raw numbers in every drain state.
    Every state links to the Bus triage screen (archiver#271).
    """
    badge = partial(_badge, triage_for="Outbox")
    if redis is None:
        if bus_init_failed():
            return badge(
                "danger",
                "not draining (init failed)",
                detail=html_escape(INIT_FAILED_DETAIL),
            )
        return badge("muted", "not draining")
    try:
        stats = await collect_outbox_stats(session)
    except Exception as exc:
        reason = str(exc)
        logger.warning("Outbox health check failed", extra={"error": reason})
        return badge("danger", "error", detail=html_escape(reason))

    age = stats.oldest_unpublished_age_seconds
    parts = [f"depth={stats.unpublished_count}"]
    if age is not None:
        parts.append(f"oldest={int(age)}s")
    parts.append(f"dead_lettered={stats.dead_lettered_count}")
    detail = html_escape(" ".join(parts))
    if stats.dead_lettered_count:
        return badge(
            "danger",
            f"{stats.dead_lettered_count} dead-lettered",
            detail=detail,
        )
    if age is not None and age > BACKLOG_WARN_AGE_SECONDS:
        return badge("warning", "backlog", detail=detail)
    return badge("success", "ok", detail=detail)


@router.get("/health/registry", response_class=HTMLResponse)
async def dashboard_health_registry(
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """HTMX partial - stored documents the current schemas reject (archiver#164).

    Such a document publishes cleanly - the announcement path checks only the
    envelope - and cannot be re-saved, so nothing else reports it until an edit
    is refused. Warning "N invalid", linking the list page; success "ok"; danger
    "error" when the database fails the sweep. ``title`` carries the documents judged.
    The sweep reads every document column once per page load: no poll, and a
    corpus of tens of rows.
    """
    try:
        report = await audit_stored_documents(session)
    except (SQLAlchemyError, OSError) as exc:
        # Not `except Exception`: a document a validator raises on is already a
        # finding, so anything else reaching here is a bug in the sweep, left to
        # 500 rather than worn as a database condition (CR 5; the Consumers
        # badge draws the same line).
        reason = str(exc)
        logger.warning("Registry document sweep failed", extra={"error": reason})
        return _badge("danger", "error", detail=html_escape(reason))
    detail = html_escape(f"{report.checked} documents checked")
    if report.findings:
        text = f"{len(report.findings)} invalid"
        label = html_escape(f"Registry: {text} - open Registry audit")
        return HTMLResponse(
            f'<a href="/dashboard/registry-audit" class="badge badge--warning" '
            f'aria-label="{label}" title="{detail}">{text}</a>'
        )
    return _badge("success", "ok", detail=detail)


@router.get("/registry-audit", response_class=HTMLResponse)
async def dashboard_registry_audit(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Every stored document the current schemas reject, with where and how to fix it."""
    report = await audit_stored_documents(session)
    return _templates.TemplateResponse(
        request,
        "registry_audit.html",
        {"user": user, "findings": finding_views(report.findings), "checked": report.checked},
    )


# Each archiver-owned consumer, paired with the ``app.state`` handle its
# lifespan branch sets and the topic its group reads. Both are gated by the
# same ARCHIVER_BUS_CONSUMER, so one badge answers for both - and a badge blind
# to half the consumers would reproduce the misleading green #147 closes.
_CONSUMERS: tuple[tuple[str, str, str], ...] = (
    ("revisions", "revisions_consumer_task", CONTENT_REVISIONS),
    ("artifacts", "artifacts_consumer_task", CONTENT_ARTIFACTS),
)


class _TaskStatus(StrEnum):
    """What a consumer task handle says about the loop behind it.

    Split from the human-readable reason so the ladder below branches on the
    enum and the ``title`` carries the prose. They were one string until CR
    round 1 finding 6: reworded text silently rerouted the badge, because the
    message *was* the control flow.
    """

    NOT_STARTED = "not started"
    RUNNING = "running"
    STOPPED = "stopped"


def _task_state(task: "asyncio.Task | None") -> tuple[_TaskStatus, str]:
    """Liveness of one consumer task, straight off ``app.state``.

    No broker round-trip: the handle is already there, and it is the only
    signal that separates "gated on and healthy" from "gated on and dead" -
    the pair an environment variable cannot tell apart (archiver#147).
    """
    if task is None:
        return _TaskStatus.NOT_STARTED, "not started"
    if not task.done():
        return _TaskStatus.RUNNING, "running"
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        # Task.exception() *raises* on a cancelled task rather than returning.
        # Shutdown cancels these, so this is a normal path, not an error one.
        return _TaskStatus.STOPPED, "stopped (cancelled)"
    reason = f"stopped ({exc!r})" if exc is not None else "stopped (clean exit)"
    return _TaskStatus.STOPPED, reason


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
    ``src.core.bus_health.collect_group_lag``, which reads the same
    ``OWNED_GROUPS`` list the rest of archiver's bus surface does. The broker's
    own alerting lives in CannObserv/broker now (archiver#193 D6) and debounces
    across two ticks; this panel deliberately shows one instant, because an
    operator can refresh. Every state links to the Bus triage screen
    (archiver#271).
    """
    badge = partial(_badge, triage_for="Consumers")
    if redis is None:
        return _no_client_badge(triage_for="Consumers")
    if not consumer_enabled(os.environ.get("ARCHIVER_BUS_CONSUMER")):
        # The one state that *is* configuration, reported as configuration: the
        # gate is what makes the dev server bus-dormant by design, so off is
        # muted, not a warning. Everything below this line is measured.
        return badge("muted", "gated off")

    states = {
        name: _task_state(getattr(request.app.state, attr, None))
        for name, attr, _topic in _CONSUMERS
    }

    lags: dict[str, GroupLag] = {}
    lag_error: str | None = None
    try:
        # The bound lives here, not on the client: this borrows the lifespan's
        # long-lived Redis client, which carries no socket timeout and cannot -
        # the group consumers issue a blocking XREADGROUP on it, and a socket
        # timeout under that block would break them. Unbounded, a broker that
        # hangs rather than refuses would block this handler forever and the
        # "lag unknown" state below would never be reached, which is the state
        # written for exactly that broker (CR round 1, finding 1).
        async with asyncio.timeout(LAG_PROBE_TIMEOUT_SECONDS):
            lags = {lag.topic: lag for lag in await collect_group_lag(redis)}
    except TimeoutError:
        # str(TimeoutError()) is empty, so a generic handler falls through to
        # repr() and the title reads "TimeoutError()" - no duration, no cause.
        # A wedged broker and a refused connection render the same badge, so
        # the title is the only place they can be told apart (CR round 2,
        # finding 11).
        lag_error = f"probe exceeded {LAG_PROBE_TIMEOUT_SECONDS}s"
        logger.warning("Consumer lag probe timed out", extra={"error": lag_error})
    except (RedisError, OSError) as exc:
        # The same tuple bus_health's own collector narrows to. Deliberately
        # not `except Exception`: a TypeError out of the collector is a bug here,
        # and rendering it as "lag unknown" reads as a broker condition and
        # sends the operator to the wrong system (CR round 1, finding 2).
        # builtins.ConnectionError is an OSError subclass, so naming it too
        # only implied a distinction that does not exist (round 2, finding 12).
        lag_error = str(exc) or repr(exc)
        logger.warning("Consumer lag probe failed", extra={"error": lag_error})

    parts = []
    for name, _attr, topic in _CONSUMERS:
        lag = lags.get(topic)
        _status, reason = states[name]
        if lag is None:
            parts.append(f"{name}={reason} pending=? dlq=?")
        else:
            pending = "group missing" if lag.pending is None else lag.pending
            parts.append(f"{name}={reason} pending={pending} dlq={lag.dlq_depth}")
    if lag_error:
        parts.append(f"lag probe failed: {lag_error}")
    detail = html_escape("; ".join(parts))

    # Liveness first: a stopped consumer is the cause, and any lag reading is
    # its symptom. Ordering the other way would report the symptom and bury
    # the thing an operator has to act on.
    statuses = {status for status, _reason in states.values()}
    if _TaskStatus.NOT_STARTED in statuses:
        return badge("danger", "not started", detail=detail)
    if _TaskStatus.STOPPED in statuses:
        return badge("danger", "stopped", detail=detail)
    if lag_error:
        # The consumers are demonstrably alive, but the depths are unknown -
        # which must not render as measured zeroes. The Redis badge alongside
        # carries the broker's own reachability.
        return badge("warning", "lag unknown", detail=detail)

    dead_lettered = sum(lag.dlq_depth for lag in lags.values())
    if dead_lettered:
        # Actionable even while both consumers run normally: every entry is a
        # frame the registry decided it could never use (archiver#162).
        return badge("danger", f"{dead_lettered} dead-lettered", detail=detail)
    if any(lag.pending is None for lag in lags.values()):
        return badge("warning", "group missing", detail=detail)
    if any(lag.pending for lag in lags.values()):
        # Raw depth, not the timer's two-tick rule: that debounces a periodic
        # alarm, where a dashboard shows one instant and the operator refreshes.
        return badge("warning", "lagging", detail=detail)
    return badge("success", "running", detail=detail)


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
                select(SourceRevision)
                .order_by(
                    SourceRevision.captured_at.desc(), SourceRevision.source_revision_id.desc()
                )
                .limit(10)
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
            .order_by(func.count().desc(), InfoSource.domain_name)
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
