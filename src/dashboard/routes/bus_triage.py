"""Dashboard Bus triage - dead-lettered outbox rows and archiver's DLQs (archiver#271).

One screen, one section for the outbox and one per queue in ``TRIAGE_DLQS``.
The routes call ``outbox_triage`` and ``dlq_triage`` directly, as the manual
replication action does, so the operator's bus writes move off curl and
``X-API-Key`` without a new API route. The rules are the cores'; what the
operator is told is ``src/dashboard/bus_triage.py``.

**Each section is its own partial**, so each paginates with the standard clamp,
fails on its own, and is what its row actions re-render. The outbox section is
a database read and works bus-dormant; a DLQ section with no broker client, or
a broker that errors or hangs, says so rather than rendering an empty table -
the API's 409 / 503 distinction, worn as a section state.

**A refusal is a 200 with a flash, never a 4xx** (``replication_actions.py``).
Ids arrive as path text, not through the API's Pydantic types, so they are
checked here before any core function sees them. An unknown queue is a 404: no
section exists to re-render.

**Who acted (D5).** The cores log each frame or row before deleting it, but not
who asked. Every action that reaches a core function writes one
``Dashboard bus triage action`` line with the acting ``AppUser``'s id - never
the email, a column #348 withholds - the queue, the ids and the outcome, which
is ``error`` when the core call raised.
"""

import asyncio
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from src.api.deps import get_db_session, get_db_session_factory, get_redis_client
from src.core.changes.diagnostics import error_text
from src.core.changes.dlq_triage import (
    TRIAGE_DLQS,
    DeadLetter,
    DiscardInterruptedError,
    ReprocessInterruptedError,
    discard_dead_letters,
    is_exact_stream_id,
    list_dead_letters,
    reprocess_dead_letters,
)
from src.core.changes.outbox_triage import (
    REARMABLE_TOPICS,
    discard_dead_lettered,
    list_dead_lettered,
    rearm_dead_lettered,
)
from src.core.logging import get_logger
from src.core.models import AppUser, ChangesOutboxRow
from src.dashboard.bus_triage import (
    Flash,
    discard_confirm,
    dlq_discard_flash,
    dlq_discard_interrupted_flash,
    duplicate_frames,
    flash_header,
    outbox_discard_flash,
    rearm_flash,
    reprocess_flash,
    reprocess_interrupted_flash,
)
from src.dashboard.deps import get_dashboard_user
from src.dashboard.exceptions import DashboardNotFound
from src.dashboard.pagination import Pagination, pagination
from src.dashboard.routes.index import INIT_FAILED_DETAIL

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisAsync

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard/bus-triage")

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PAGE_PATH = "/dashboard/bus-triage"
OUTBOX_QUEUE = "changes_outbox"
"""The audit line's ``queue`` for an outbox action: the table, as journald knows it."""

# The listing borrows the lifespan's Redis client, which carries no socket
# timeout (see LAG_PROBE_TIMEOUT_SECONDS in routes/index.py), so a hung broker
# would hang the page. Reads only: a write cancelled mid-loop would lose the
# progress DiscardInterruptedError / ReprocessInterruptedError exist to report.
BROKER_READ_TIMEOUT_SECONDS = 5.0

_DORMANT = "Bus dormant - no ARCHIVER_REDIS_URL, so there is no broker to read."
_INIT_FAILED = f"Bus init failed - {INIT_FAILED_DETAIL}."

DlqState = Literal["ok", "dormant", "init_failed", "unreadable"]


@dataclass(frozen=True, slots=True)
class OutboxRowView:
    """One dead-lettered outbox row, as the section renders it."""

    row_id: str
    topic: str
    event_type: str | None
    payload: object
    last_error: str | None
    publish_attempts: int
    created_at: datetime | None
    dead_lettered_at: datetime | None
    rearmable: bool


@dataclass(frozen=True, slots=True)
class OutboxSection:
    """The outbox section's context."""

    rows: list[OutboxRowView]
    has_more: bool
    limit: int
    offset: int
    url: str = f"{PAGE_PATH}/outbox"
    dom_id: str = "triage-outbox"


@dataclass(frozen=True, slots=True)
class DlqSection:
    """One DLQ section's context. ``entries`` is meaningful only when ``state`` is ok."""

    dlq: str
    state: DlqState
    limit: int
    offset: int
    message: str | None = None
    entries: list[DeadLetter] = field(default_factory=list)
    has_more: bool = False
    duplicates: set[str] = field(default_factory=set)
    confirms: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"{PAGE_PATH}/dlq/{self.dlq}"

    @property
    def dom_id(self) -> str:
        return "triage-dlq-" + self.dlq.replace(".", "-")


def _row_view(row: ChangesOutboxRow) -> OutboxRowView:
    return OutboxRowView(
        row_id=str(row.id),
        topic=row.topic,
        event_type=row.payload.get("event_type") if isinstance(row.payload, dict) else None,
        payload=row.payload,
        last_error=row.last_error,
        publish_attempts=row.publish_attempts,
        created_at=row.created_at,
        dead_lettered_at=row.dead_lettered_at,
        rearmable=row.topic in REARMABLE_TOPICS,
    )


async def _outbox_section(session: AsyncSession, page: Pagination) -> OutboxSection:
    rows, has_more = await list_dead_lettered(session, limit=page.limit, offset=page.offset)
    return OutboxSection(
        rows=[_row_view(r) for r in rows],
        has_more=has_more,
        limit=page.limit,
        offset=page.offset,
    )


def _no_client_state() -> tuple[DlqState, str]:
    """Why there is no broker client: configured off, or init raised with the URL set."""
    if os.environ.get("ARCHIVER_REDIS_URL", "").strip():
        return "init_failed", _INIT_FAILED
    return "dormant", _DORMANT


async def _dlq_section(redis: "RedisAsync | None", dlq: str, page: Pagination) -> DlqSection:
    window = {"dlq": dlq, "limit": page.limit, "offset": page.offset}
    if redis is None:
        state, message = _no_client_state()
        return DlqSection(state=state, message=message, **window)
    try:
        async with asyncio.timeout(BROKER_READ_TIMEOUT_SECONDS):
            entries, has_more = await list_dead_letters(
                redis, dlq, limit=page.limit, offset=page.offset
            )
    except TimeoutError:
        message = f"broker read exceeded {BROKER_READ_TIMEOUT_SECONDS}s"
        logger.warning("Bus triage DLQ read timed out", extra={"dlq": dlq, "error": message})
        return DlqSection(state="unreadable", message=message, **window)
    except (RedisError, OSError) as exc:
        message = error_text(exc)
        logger.warning("Bus triage DLQ read failed", extra={"dlq": dlq, "error": message})
        return DlqSection(state="unreadable", message=message, **window)
    return DlqSection(
        state="ok",
        entries=entries,
        has_more=has_more,
        duplicates=duplicate_frames(entries),
        confirms={e.entry_id: discard_confirm(e) for e in entries},
        **window,
    )


def _require_triage_dlq(dlq: str) -> str:
    if dlq not in TRIAGE_DLQS:
        raise DashboardNotFound(f"Not a dead-letter queue archiver triages: {dlq}")
    return dlq


@dataclass(slots=True)
class _Audit:
    """The outcome an action records; ``error`` until the core call returns."""

    outcome: str = "error"


@contextmanager
def _audited(user: AppUser, *, action: str, queue: str, ids: list[str]) -> Iterator[_Audit]:
    """D5: who asked for a triage write, beside the core's own frame log.

    Written on the way out whatever happened, so a core call that raises still
    leaves its line - ``outcome="error"`` - before the error handler takes it.
    """
    audit = _Audit()
    try:
        yield audit
    finally:
        logger.info(
            "Dashboard bus triage action",
            extra={
                "app_user_id": str(user.id),
                "action": action,
                "queue": queue,
                "ids": ids,
                "outcome": audit.outcome,
            },
        )


def _render_outbox(request: Request, section: OutboxSection, flash: Flash) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "bus_triage/_outbox_section.html",
        {"outbox": section},
        headers={"HX-Trigger": flash_header(flash)},
    )


def _render_dlq(request: Request, section: DlqSection, flash: Flash | None = None) -> HTMLResponse:
    headers = {"HX-Trigger": flash_header(flash)} if flash else None
    return _templates.TemplateResponse(
        request, "bus_triage/_dlq_section.html", {"section": section}, headers=headers
    )


# ---------------------------------------------------------------------------
# Page and sections
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def bus_triage_page(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    redis: "RedisAsync | None" = Depends(get_redis_client),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """Every section's first page, rendered server-side.

    The queues are read at once, so a hung broker costs the page one
    ``BROKER_READ_TIMEOUT_SECONDS``, not one per queue.
    """
    outbox = await _outbox_section(session, page)
    dlqs = await asyncio.gather(*(_dlq_section(redis, dlq, page) for dlq in TRIAGE_DLQS))
    return _templates.TemplateResponse(
        request,
        "bus_triage/index.html",
        {"user": user, "outbox": outbox, "dlq_sections": dlqs},
    )


@router.get("/outbox", response_class=HTMLResponse)
async def bus_triage_outbox(
    request: Request,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """The outbox section alone: pagination and re-list."""
    return _templates.TemplateResponse(
        request,
        "bus_triage/_outbox_section.html",
        {"outbox": await _outbox_section(session, page)},
    )


@router.get("/dlq/{dlq}", response_class=HTMLResponse)
async def bus_triage_dlq(
    request: Request,
    dlq: str,
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """One DLQ section alone: pagination and re-list."""
    return _render_dlq(request, await _dlq_section(redis, _require_triage_dlq(dlq), page))


# ---------------------------------------------------------------------------
# Outbox actions
# ---------------------------------------------------------------------------


def _is_row_id(row_id: str) -> bool:
    """Whether ``row_id`` parses as a ULID - what the core's ``ULID.from_str`` needs.

    Strict, as the parser is: Crockford base32 in upper case only, so a
    hand-typed lowercase id is refused here rather than raising in the core.
    """
    try:
        ULID.from_str(row_id)
    except ValueError:
        return False
    return True


@router.post("/outbox/{row_id}/rearm", response_class=HTMLResponse)
async def bus_triage_outbox_rearm(
    request: Request,
    row_id: str,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """Return one dead-lettered row to the drain's queue."""
    if not _is_row_id(row_id):
        flash: Flash = ("error", f"Not an outbox row id: {row_id}. Nothing was changed.")
    else:
        with _audited(user, action="rearm", queue=OUTBOX_QUEUE, ids=[row_id]) as audit:
            [result] = await rearm_dead_lettered(session, [row_id])
            audit.outcome = result.outcome
        flash = rearm_flash(result)
    return _render_outbox(request, await _outbox_section(session, page), flash)


@router.post("/outbox/{row_id}/discard", response_class=HTMLResponse)
async def bus_triage_outbox_discard(
    request: Request,
    row_id: str,
    user: AppUser = Depends(get_dashboard_user),
    session: AsyncSession = Depends(get_db_session),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """Delete one dead-lettered row, logged in full by the core first."""
    if not _is_row_id(row_id):
        flash: Flash = ("error", f"Not an outbox row id: {row_id}. Nothing was deleted.")
    else:
        with _audited(user, action="discard", queue=OUTBOX_QUEUE, ids=[row_id]) as audit:
            outcome = await discard_dead_lettered(session, [row_id])
            audit.outcome = "discarded" if outcome.discarded else "not_found"
        flash = outbox_discard_flash(outcome, row_id)
    return _render_outbox(request, await _outbox_section(session, page), flash)


# ---------------------------------------------------------------------------
# DLQ actions
# ---------------------------------------------------------------------------


def _dlq_refusal(redis: "RedisAsync | None", entry_id: str) -> Flash | None:
    """Why a DLQ action cannot reach the core at all, or ``None`` if it can."""
    if redis is None:
        _state, message = _no_client_state()
        return "error", f"{message} Nothing was changed."
    if not is_exact_stream_id(entry_id):
        return "error", f"Not an exact stream id: {entry_id}. Nothing was changed."
    return None


@router.post("/dlq/{dlq}/{entry_id}/discard", response_class=HTMLResponse)
async def bus_triage_dlq_discard(
    request: Request,
    dlq: str,
    entry_id: str,
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """``XDEL`` one entry, its frame logged by the core first. Does not filter by owner (D4)."""
    _require_triage_dlq(dlq)
    flash = _dlq_refusal(redis, entry_id)
    if flash is None:
        with _audited(user, action="discard", queue=dlq, ids=[entry_id]) as audit:
            try:
                result = await discard_dead_letters(redis, dlq, [entry_id])
            except DiscardInterruptedError as e:
                audit.outcome = "interrupted"
                flash = dlq_discard_interrupted_flash(e)
            else:
                audit.outcome = "discarded" if result.discarded else "not_found"
                flash = dlq_discard_flash(result, dlq, entry_id)
    return _render_dlq(request, await _dlq_section(redis, dlq, page), flash)


@router.post("/dlq/{dlq}/{entry_id}/reprocess", response_class=HTMLResponse)
async def bus_triage_dlq_reprocess(
    request: Request,
    dlq: str,
    entry_id: str,
    user: AppUser = Depends(get_dashboard_user),
    redis: "RedisAsync | None" = Depends(get_redis_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_db_session_factory),
    page: Pagination = Depends(pagination),
) -> HTMLResponse:
    """Run one owned entry through its queue's handler; the core deletes what it settles."""
    _require_triage_dlq(dlq)
    flash = _dlq_refusal(redis, entry_id)
    if flash is None:
        with _audited(user, action="reprocess", queue=dlq, ids=[entry_id]) as audit:
            try:
                [result] = await reprocess_dead_letters(
                    redis, dlq, [entry_id], session_factory=session_factory
                )
            except ReprocessInterruptedError as e:
                audit.outcome = "interrupted"
                flash = reprocess_interrupted_flash(e)
            else:
                audit.outcome = result.outcome
                flash = reprocess_flash(result)
    return _render_dlq(request, await _dlq_section(redis, dlq, page), flash)
