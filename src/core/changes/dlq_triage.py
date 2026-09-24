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
0, so an untriaged entry must stay visible. That leaves broker's ``+xtrim``
grant on these two queues with no caller.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from co_core.pure.adapters.bus.envelope import from_wire
from co_core.pure.adapters.bus.exceptions import BusMessageAnomaly
from co_core.pure.adapters.bus.streams import dlq_name

from src.core.bus_health import OWNED_GROUPS
from src.core.changes.diagnostics import error_text
from src.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

_SOURCE_TOPIC_BY_DLQ: dict[str, str] = {dlq_name(g.topic): g.topic for g in OWNED_GROUPS}

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
"""An exact stream id, ``<ms>-<seq>``. Anything looser is a range to ``XRANGE``:
``-``/``+`` are the whole stream, and a bare ``<ms>`` is every entry in that
millisecond."""
_STREAM_ID = re.compile(STREAM_ID_PATTERN)


class NotTriageableError(ValueError):
    """A stream outside ``TRIAGE_DLQS`` - above all, the stream a DLQ copies."""

    def __init__(self, dlq: str) -> None:
        super().__init__(f"not a dead-letter queue archiver triages: {dlq!r}")
        self.dlq = dlq


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """One DLQ entry, described for the operator deciding about it.

    ``dead_lettered_at`` comes from the entry id: ``dead_letter`` records no
    provenance (cannobserv#474), so the time is the only way back to the
    journald line that says why the entry was parked.
    """

    entry_id: str
    dead_lettered_at: datetime
    fields: dict[str, str]
    event_type: str | None
    decodes: bool
    decode_error: str | None


@dataclass(frozen=True, slots=True)
class DiscardResult:
    """Which requested ids were deleted, and which were not in the queue."""

    discarded: tuple[str, ...]
    not_found: tuple[str, ...]


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


def _describe(source_topic: str, entry_id: str, fields: dict[str, str]) -> DeadLetter:
    """Try the frame against the running co-core: decoding is the skew question."""
    try:
        from_wire(fields, topic=source_topic, message_id=entry_id)
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
    )


async def list_dead_letters(
    client: Redis, dlq: str, *, limit: int, offset: int
) -> tuple[list[DeadLetter], bool]:
    """One page of ``dlq``, oldest first, and whether more follow.

    Offset over ``XRANGE`` reads ``offset`` entries it then drops. That is fine at
    a queue's resting depth of 0 and the handful a real dead-letter leaves; a
    queue deep enough for it to matter is a broker finding already.
    """
    source_topic = _require_triageable(dlq)
    count = min(offset + limit + 1, _MAX_XRANGE_COUNT)
    raw = await client.xrange(dlq, count=count)
    window = raw[offset : offset + limit + 1]
    entries = [
        _describe(source_topic, _text(eid), {_text(k): _text(v) for k, v in fields.items()})
        for eid, fields in window[:limit]
    ]
    return entries, len(window) > limit


async def discard_dead_letters(client: Redis, dlq: str, entry_ids: Iterable[str]) -> DiscardResult:
    """``XDEL`` each named entry from ``dlq``, logging its frame first.

    The log line is archiver's record of what was destroyed. Broker's evidence
    capture runs on its own tick, so an entry discarded before the next one
    would otherwise leave nothing. An id already gone - never there, or taken by
    a concurrent discard between the read and the delete - is ``not_found``.

    Every id is checked against ``STREAM_ID_PATTERN`` before any command is
    sent, so one bad id deletes nothing.
    """
    _require_triageable(dlq)
    requested = list(dict.fromkeys(entry_ids))
    inexact = [entry_id for entry_id in requested if not _STREAM_ID.fullmatch(entry_id)]
    if inexact:
        raise ValueError(f"not an exact stream id: {inexact!r}")
    discarded: list[str] = []
    not_found: list[str] = []
    for entry_id in requested:
        entries = await client.xrange(dlq, min=entry_id, max=entry_id)
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
        if await client.xdel(dlq, entry_id):
            discarded.append(entry_id)
        else:
            not_found.append(entry_id)
    return DiscardResult(discarded=tuple(discarded), not_found=tuple(not_found))
