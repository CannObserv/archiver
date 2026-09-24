"""Triage for the dead-letter queues archiver drains (archiver#238).

CannObserv/broker#1 Phase 5 split the old drainer role in two. **Broker**
detects a non-resting ``*.dlq``, dumps its entries on first sight and names the
owner. **The stream's own consumer** reads the payloads, decides, and deletes.
Archiver consumes ``content.revisions`` and ``content.artifacts`` with a group,
so their two queues are archiver's to triage and no others are.

What lands in them, and the disposition it gets:

- **Handler poison** (``content.revisions`` only: ``InvalidFingerprintError``,
  ``InvalidInfoSourceIdError``). Deterministic producer data. Discard it, and
  file on the producer.
- **An undecodable frame** (both queues). Usually the same. The one exception
  is *version skew*: a producer shipped an ``event_type`` or schema before
  archiver upgraded co-core, and after the upgrade the frame decodes.

This module lists, discards and reprocesses. co-core >= 0.19.1's
``dead_letter`` records why each entry was parked (cannobserv#474), and
quarantine writes a reason prefix per path, so the listing tells the two apart
even once both decode.

**Reprocess runs the consumer's own handler in-process, then ``XDEL``s.** It
never re-``XADD``s onto the source stream: broker's ACL refuses that, it would
forge another service's stream, and on a broadcast stream every other group
would see the replay. The handlers are idempotent under redelivery, which is
what makes a second run of an already-applied entry - a duplicate
dead-lettering, a retry after a lost ``XDEL`` reply - harmless. **Only owned
entries run**: a fact stream's DLQ is shared by every consuming service's
group, so an entry another group parked, or one with no provenance to say, is
left for its owner or for a discard.

**Disposal is ``XDEL`` by id, never ``XTRIM``.** A cap discards entries whether
or not anyone read them, and broker's detector rests on the resting depth being
0, so an untriaged entry must stay visible. Broker's ACL matches: archiver
holds ``+xdel`` on these two queues and, since CannObserv/broker#59 (live
2026-09-24), no ``+xtrim``.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from co_core.pure.adapters.bus.dead_letter import DeadLetterProvenance, split_dead_letter
from co_core.pure.adapters.bus.envelope import from_wire
from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS, CONTENT_REVISIONS, dlq_name
from redis.exceptions import RedisError

from src.core.bus_health import OWNED_GROUPS
from src.core.changes import artifacts_consumer
from src.core.changes import consumer as revisions_consumer
from src.core.changes.diagnostics import error_text
from src.core.changes.group_consumer import REASON_HANDLER_POISON, REASON_UNDECODABLE
from src.core.logging import get_logger

if TYPE_CHECKING:
    from co_core_aio.bus import BusMessage
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)

_SOURCE_TOPIC_BY_DLQ: dict[str, str] = {dlq_name(g.topic): g.topic for g in OWNED_GROUPS}
_GROUP_BY_DLQ: dict[str, str] = {dlq_name(g.topic): g.group for g in OWNED_GROUPS}

ParkedAs = Literal["handler_poison", "undecodable"]
_PARKED_AS_BY_PREFIX: dict[str, ParkedAs] = {
    f"{REASON_HANDLER_POISON}: ": "handler_poison",
    f"{REASON_UNDECODABLE}: ": "undecodable",
}

TRIAGE_DLQS: tuple[str, ...] = tuple(_SOURCE_TOPIC_BY_DLQ)
"""The queues this module will read or delete from, derived from ``OWNED_GROUPS``.

The drainer is the stream's consumer, so a group archiver runs is a queue it
triages. **One decision with broker's** ``(+xdel ~content.revisions.dlq
~content.artifacts.dlq)`` selector in ``deploy/redis-acl.conf``: a new owned
group joins this set automatically, and its discard fails NOPERM until the
grant follows."""

# XRANGE's COUNT is a signed 64-bit integer; ``offset`` alone may reach it.
_MAX_XRANGE_COUNT = 2**63 - 1

STREAM_ID_PATTERN = r"^[0-9]+-[0-9]+$"
"""The *shape* of an exact stream id, ``<ms>-<seq>`` - what OpenAPI can state.
``is_exact_stream_id`` is the whole rule."""
_STREAM_ID = re.compile(STREAM_ID_PATTERN)
_UINT64_MAX = 2**64 - 1


@dataclass(frozen=True, slots=True)
class _Reprocessor:
    """A queue's handler, and which of its exceptions mean *poison*."""

    handle: Callable[[async_sessionmaker[AsyncSession], BusMessage], Awaitable[bool]]
    poison_errors: tuple[type[BaseException], ...]


_REPROCESSORS: dict[str, _Reprocessor] = {
    dlq_name(CONTENT_REVISIONS): _Reprocessor(
        handle=revisions_consumer.handle_message,
        poison_errors=revisions_consumer.POISON_ERRORS,
    ),
    # content.artifacts has no poison class: a frame decodes or it does not.
    dlq_name(CONTENT_ARTIFACTS): _Reprocessor(
        handle=artifacts_consumer.handle_message, poison_errors=()
    ),
}
"""The handler each consumer loop runs, keyed by its DLQ - the same function, so
a reprocessed entry is decided exactly as a live delivery would be."""

ReprocessOutcome = Literal[
    "reprocessed", "not_found", "not_owned", "undecodable", "rejected", "failed", "deferred"
]


class NotTriageableError(ValueError):
    """A stream outside ``TRIAGE_DLQS`` - above all, the stream a DLQ copies."""

    def __init__(self, dlq: str) -> None:
        super().__init__(f"not a dead-letter queue archiver triages: {dlq!r}")
        self.dlq = dlq


class DiscardInterruptedError(Exception):
    """The broker failed part-way through a discard, and what had happened by then.

    ``discarded`` and ``not_found`` are settled. ``in_doubt`` is the id whose
    ``XDEL`` was in flight: it may have landed with its reply lost, so only a
    re-list can say. ``None`` when the failure was a read, which deletes nothing.
    Ids after it were never attempted.
    """

    def __init__(
        self,
        dlq: str,
        *,
        discarded: tuple[str, ...],
        not_found: tuple[str, ...],
        in_doubt: str | None,
    ) -> None:
        super().__init__(
            f"broker failed during discard from {dlq!r} after {len(discarded)} deletion(s)"
            + (f"; {in_doubt} in doubt" if in_doubt else "")
        )
        self.dlq = dlq
        self.discarded = discarded
        self.not_found = not_found
        self.in_doubt = in_doubt


@dataclass(frozen=True, slots=True)
class ReprocessResult:
    """What happened to one requested entry. Only ``reprocessed`` removed it.

    ``detail`` says why an entry stayed: the group that parked it
    (``not_owned``), or the error (``undecodable``, ``rejected``, ``failed``).
    """

    entry_id: str
    outcome: ReprocessOutcome
    detail: str | None = None


class ReprocessInterruptedError(Exception):
    """The broker failed part-way through a reprocess, and what had happened by then.

    ``results`` are settled. ``in_doubt`` is the id whose ``XDEL`` was in
    flight: its handler had already committed, so a retry runs it again, which
    idempotency makes harmless. ``None`` when the failure was a read.
    """

    def __init__(
        self, dlq: str, *, results: tuple[ReprocessResult, ...], in_doubt: str | None
    ) -> None:
        super().__init__(
            f"broker failed during reprocess from {dlq!r} after {len(results)} entr"
            + ("y" if len(results) == 1 else "ies")
            + (f"; {in_doubt} in doubt" if in_doubt else "")
        )
        self.dlq = dlq
        self.results = results
        self.in_doubt = in_doubt


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """One DLQ entry, described for the operator deciding about it.

    ``provenance`` is what co-core >= 0.19.1's ``dead_letter`` recorded
    (cannobserv#474): the original id, the group and consumer that parked it,
    and why. Every field is ``None`` on an entry written before that, where
    ``dead_lettered_at`` (from the entry id) is still the way back to the
    journald line. ``parked_as`` reads the reason's prefix; ``owned`` is whether
    archiver's own group for this queue's topic parked it - a fact stream's DLQ
    is shared by every consuming service's group, and only owned entries are
    archiver's handlers' to reprocess.
    """

    entry_id: str
    dead_lettered_at: datetime
    fields: dict[str, str]
    event_type: str | None
    decodes: bool
    decode_error: str | None
    provenance: DeadLetterProvenance
    parked_as: ParkedAs | None
    owned: bool


@dataclass(frozen=True, slots=True)
class DiscardResult:
    """Which requested ids were deleted, and which were not in the queue."""

    discarded: tuple[str, ...]
    not_found: tuple[str, ...]


def is_exact_stream_id(value: str) -> bool:
    """Whether ``value`` names exactly one stream entry.

    Anything looser is a range to ``XRANGE``: ``-``/``+`` are the whole stream,
    and a bare ``<ms>`` is every entry in that millisecond. Each half is also
    bounded at uint64, because Redis parses it as one and answers ``ERR Invalid
    stream ID`` past it - an error that would otherwise land mid-discard, after
    the ids before it were deleted. fakeredis returns an empty range instead, so
    no stream test can see that case; this check is where it is held.
    """
    if not _STREAM_ID.fullmatch(value):
        return False
    ms, seq = value.split("-")
    return int(ms) <= _UINT64_MAX and int(seq) <= _UINT64_MAX


def _exact_ids(entry_ids: Iterable[str]) -> list[str]:
    """``entry_ids`` deduplicated in order, or ``ValueError`` naming the inexact ones."""
    requested = list(dict.fromkeys(entry_ids))
    inexact = [entry_id for entry_id in requested if not is_exact_stream_id(entry_id)]
    if inexact:
        raise ValueError(f"not an exact stream id: {inexact!r}")
    return requested


def _require_triageable(dlq: str) -> str:
    """Return the source topic for ``dlq``, or raise ``NotTriageableError``."""
    try:
        return _SOURCE_TOPIC_BY_DLQ[dlq]
    except KeyError as e:
        raise NotTriageableError(dlq) from e


def _text(value: bytes | str) -> str:
    """Redis returns bytes unless the client decodes. A frame too broken to be
    UTF-8 is still shown, escaped, rather than failing the whole listing."""
    return value.decode(errors="backslashreplace") if isinstance(value, bytes) else value


def _entry_time(entry_id: str) -> datetime:
    """The millisecond timestamp half of a stream id, as UTC."""
    millis = int(entry_id.split("-", 1)[0])
    return datetime.fromtimestamp(millis / 1000, tz=UTC)


def _parked_as(reason: str | None) -> ParkedAs | None:
    """The quarantine path that wrote ``reason``, or ``None`` if it is not ours."""
    if reason is None:
        return None
    for prefix, kind in _PARKED_AS_BY_PREFIX.items():
        if reason.startswith(prefix):
            return kind
    return None


def _describe(dlq: str, entry_id: str, fields: dict[str, str]) -> DeadLetter:
    """Try the frame against the running co-core: decoding is the skew question.

    The decode is of the wire half, as a reprocess would hand it to a handler.
    """
    wire, provenance = split_dead_letter(fields)
    try:
        from_wire(wire, topic=_SOURCE_TOPIC_BY_DLQ[dlq], message_id=entry_id)
    except BusMessageAnomaly as exc:
        decode_error: str | None = error_text(exc)
    else:
        decode_error = None
    return DeadLetter(
        entry_id=entry_id,
        dead_lettered_at=_entry_time(entry_id),
        fields=fields,
        event_type=fields.get("event_type"),
        decodes=decode_error is None,
        decode_error=decode_error,
        provenance=provenance,
        parked_as=_parked_as(provenance.reason),
        owned=provenance.group == _GROUP_BY_DLQ[dlq],
    )


async def list_dead_letters(
    client: Redis, dlq: str, *, limit: int, offset: int
) -> tuple[list[DeadLetter], bool]:
    """One page of ``dlq``, oldest first, and whether more follow.

    Offset over ``XRANGE`` reads ``offset`` entries it then drops. That is fine at
    a queue's resting depth of 0 and the handful a real dead-letter leaves; a
    queue deep enough for it to matter is a broker finding already.
    """
    _require_triageable(dlq)
    count = min(offset + limit + 1, _MAX_XRANGE_COUNT)
    raw = await client.xrange(dlq, count=count)
    window = raw[offset : offset + limit + 1]
    entries = [
        _describe(dlq, _text(eid), {_text(k): _text(v) for k, v in fields.items()})
        for eid, fields in window[:limit]
    ]
    return entries, len(window) > limit


async def discard_dead_letters(client: Redis, dlq: str, entry_ids: Iterable[str]) -> DiscardResult:
    """``XDEL`` each named entry from ``dlq``, logging its frame first.

    The log line is archiver's record of what was destroyed. Broker's evidence
    capture runs on its own tick, so an entry discarded before the next one
    would otherwise leave nothing. An id already gone - never there, or taken by
    a concurrent discard between the read and the delete - is ``not_found``.

    Every id is checked with ``is_exact_stream_id`` before any command is sent,
    so one bad id deletes nothing. A broker failure part-way through raises
    ``DiscardInterruptedError`` carrying the progress so far: without it, a
    retry would report ids this call already deleted as ``not_found``.
    """
    _require_triageable(dlq)
    requested = _exact_ids(entry_ids)
    discarded: list[str] = []
    not_found: list[str] = []

    def interrupted(exc: BaseException, in_doubt: str | None) -> DiscardInterruptedError:
        err = DiscardInterruptedError(
            dlq, discarded=tuple(discarded), not_found=tuple(not_found), in_doubt=in_doubt
        )
        logger.error(
            "Discard interrupted by a broker failure",
            extra={
                "dlq": dlq,
                "discarded": list(err.discarded),
                "in_doubt": in_doubt,
                "error": error_text(exc),
            },
        )
        return err

    for entry_id in requested:
        try:
            entries = await client.xrange(dlq, min=entry_id, max=entry_id)
        except (RedisError, OSError) as e:
            raise interrupted(e, None) from e
        if not entries:
            not_found.append(entry_id)
            continue
        _, raw_fields = entries[0]
        logger.info(
            "Discarding dead letter",
            extra={
                "dlq": dlq,
                "entry_id": entry_id,
                "dead_lettered_at": _entry_time(entry_id).isoformat(),
                "fields": {_text(k): _text(v) for k, v in raw_fields.items()},
            },
        )
        try:
            deleted = await client.xdel(dlq, entry_id)
        except (RedisError, OSError) as e:
            raise interrupted(e, entry_id) from e
        if deleted:
            discarded.append(entry_id)
        else:
            not_found.append(entry_id)
    return DiscardResult(discarded=tuple(discarded), not_found=tuple(not_found))


async def reprocess_dead_letters(
    client: Redis,
    dlq: str,
    entry_ids: Iterable[str],
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[ReprocessResult, ...]:
    """Run each owned entry through its queue's handler; ``XDEL`` what it settles.

    Per entry, in order: read it; skip it unless archiver's own group for this
    topic parked it; decode the wire half with the running co-core; hand the
    handler that message under the entry's original id, so its log lines name
    the id the source stream knew. Only a settled entry is deleted, after its
    frame is logged, and a failure is per entry: the rest still run.

    Ids are checked with ``is_exact_stream_id`` before anything runs. A broker
    failure raises ``ReprocessInterruptedError`` with the results so far.
    """
    source_topic = _require_triageable(dlq)
    requested = _exact_ids(entry_ids)
    reprocessor = _REPROCESSORS[dlq]
    own_group = _GROUP_BY_DLQ[dlq]
    results: list[ReprocessResult] = []

    def interrupted(exc: BaseException, in_doubt: str | None) -> ReprocessInterruptedError:
        err = ReprocessInterruptedError(dlq, results=tuple(results), in_doubt=in_doubt)
        logger.error(
            "Reprocess interrupted by a broker failure",
            extra={
                "dlq": dlq,
                "reprocessed": [r.entry_id for r in results if r.outcome == "reprocessed"],
                "in_doubt": in_doubt,
                "error": error_text(exc),
            },
        )
        return err

    def left(
        entry_id: str,
        outcome: ReprocessOutcome,
        detail: str | None = None,
        *,
        exc: BaseException | None = None,
    ) -> None:
        results.append(ReprocessResult(entry_id=entry_id, outcome=outcome, detail=detail))
        if outcome != "not_found":
            logger.warning(
                "Dead letter left in queue by reprocess",
                extra={"dlq": dlq, "entry_id": entry_id, "outcome": outcome, "detail": detail},
                # Only ``failed`` carries its stack: it is the catch-all, so the
                # one outcome that can be a handler bug rather than a verdict.
                exc_info=exc,
            )

    for entry_id in requested:
        try:
            entries = await client.xrange(dlq, min=entry_id, max=entry_id)
        except (RedisError, OSError) as e:
            raise interrupted(e, None) from e
        if not entries:
            left(entry_id, "not_found")
            continue
        _, raw_fields = entries[0]
        fields = {_text(k): _text(v) for k, v in raw_fields.items()}
        wire, provenance = split_dead_letter(fields)

        if provenance.group != own_group:
            left(
                entry_id,
                "not_owned",
                "no provenance: written before co-core 0.19.1"
                if provenance.group is None
                else f"parked by {provenance.group!r}, not {own_group!r}",
            )
            continue
        try:
            message = from_wire(
                wire, topic=source_topic, message_id=provenance.source_id or entry_id
            )
        except BusMessageAnomaly as exc:
            left(entry_id, "undecodable", error_text(exc))
            continue
        try:
            settled = await reprocessor.handle(session_factory, message)
        except reprocessor.poison_errors as exc:
            left(entry_id, "rejected", error_text(exc))
            continue
        except Exception as exc:
            # Per entry, like the consumer loop's own catch: a transient failure
            # (the database down) leaves this one for a retry, not the rest.
            left(entry_id, "failed", error_text(exc), exc=exc)
            continue
        if not settled:
            left(entry_id, "deferred")
            continue

        logger.info(
            "Reprocessed dead letter",
            extra={
                "dlq": dlq,
                "entry_id": entry_id,
                "source_id": provenance.source_id,
                "dead_lettered_at": _entry_time(entry_id).isoformat(),
                "fields": fields,
            },
        )
        try:
            await client.xdel(dlq, entry_id)
        except (RedisError, OSError) as e:
            raise interrupted(e, entry_id) from e
        results.append(ReprocessResult(entry_id=entry_id, outcome="reprocessed"))
    return tuple(results)
