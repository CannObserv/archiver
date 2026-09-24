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

This module lists and discards. **Reprocessing is deferred**: nothing needs it
yet, and until co-core-aio's ``dead_letter`` records why an entry was parked
(cannobserv#474), a skew frame and a handler rejection look the same once both
decode. When it lands it runs the consumer's own handler in-process and then
``XDEL``s. It never re-``XADD``s onto the source stream, which broker's ACL
refuses and which would forge another service's stream.

**Disposal is ``XDEL`` by id, never ``XTRIM``.** A cap discards entries whether
or not anyone read them, and broker's detector rests on the resting depth being
0, so an untriaged entry must stay visible. Broker's ACL matches: archiver
holds ``+xdel`` on these two queues and, since CannObserv/broker#59 (live
2026-09-24), no ``+xtrim``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from co_core.pure.adapters.bus.dead_letter import DeadLetterProvenance, split_dead_letter
from co_core.pure.adapters.bus.envelope import from_wire
from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.adapters.bus.streams import dlq_name
from redis.exceptions import RedisError

from src.core.bus_health import OWNED_GROUPS
from src.core.changes.diagnostics import error_text
from src.core.changes.group_consumer import REASON_HANDLER_POISON, REASON_UNDECODABLE
from src.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

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
    requested = list(dict.fromkeys(entry_ids))
    inexact = [entry_id for entry_id in requested if not is_exact_stream_id(entry_id)]
    if inexact:
        raise ValueError(f"not an exact stream id: {inexact!r}")
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
