"""DLQ triage: listing and discarding the two queues archiver drains (archiver#238).

Exercised against fakeredis so the stream commands (XRANGE / XDEL) are real,
not mocked. Reprocessing is deliberately absent - see the module docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from ulid import ULID

from src.core.changes import dlq_triage
from src.core.changes.dlq_triage import (
    TRIAGE_DLQS,
    NotTriageableError,
    discard_dead_letters,
    is_exact_stream_id,
    list_dead_letters,
)

REVISIONS_DLQ = "content.revisions.dlq"
ARTIFACTS_DLQ = "content.artifacts.dlq"


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


def _observed_frame() -> dict[str, str]:
    """A well-formed ``source_revision_observed`` wire map, as ``dead_letter`` copies it."""
    event = SourceRevisionObservedEvent(
        occurred_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        info_source_id=str(ULID()),
        extracted_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
        content_size_bytes=2048,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="file:///var/lib/replicator/blobs/ab/cd/deadbeef.bin",
        command_id="cmd-dlq",
    )
    return to_wire(event)


# --- the allowlist ---


def test_triage_dlqs_are_the_two_queues_broker_grants_xdel_on():
    """One decision with broker's ``(+xdel ~content.revisions.dlq ~content.artifacts.dlq)``
    selector in ``deploy/redis-acl.conf``: widen one, widen the other. A new
    consumer group joins this set by being added to ``OWNED_GROUPS``, and its
    discard then needs the matching grant or it fails NOPERM."""
    assert TRIAGE_DLQS == (REVISIONS_DLQ, ARTIFACTS_DLQ)


async def test_listing_a_queue_outside_the_allowlist_is_refused(fake_redis):
    with pytest.raises(NotTriageableError):
        await list_dead_letters(fake_redis, "content.fetch.dlq", limit=10, offset=0)


async def test_discarding_from_a_stream_outside_the_allowlist_is_refused(fake_redis):
    """The guard that matters most: an XDEL aimed at the stream a DLQ copies."""
    entry_id = await fake_redis.xadd("content.revisions", _observed_frame())
    with pytest.raises(NotTriageableError):
        await discard_dead_letters(fake_redis, "content.revisions", [entry_id.decode()])
    assert await fake_redis.xlen("content.revisions") == 1


# --- listing ---


async def test_list_describes_a_decodable_entry(fake_redis):
    frame = _observed_frame()
    entry_id = (await fake_redis.xadd(REVISIONS_DLQ, frame)).decode()

    entries, has_more = await list_dead_letters(fake_redis, REVISIONS_DLQ, limit=10, offset=0)

    assert has_more is False
    [entry] = entries
    assert entry.entry_id == entry_id
    assert entry.fields == frame
    assert entry.event_type == "source_revision_observed"
    assert entry.decodes is True
    assert entry.decode_error is None


async def test_list_dates_each_entry_from_its_stream_id(fake_redis):
    """The id's millisecond part is when ``dead_letter`` wrote it - until
    cannobserv#474 ships provenance, the one handle back to the journald line
    that says why."""
    await fake_redis.xadd(REVISIONS_DLQ, _observed_frame(), id="1727179200123-0")

    [entry], _ = await list_dead_letters(fake_redis, REVISIONS_DLQ, limit=10, offset=0)

    assert entry.dead_lettered_at == datetime(2024, 9, 24, 12, 0, 0, 123000, tzinfo=UTC)


async def test_list_reports_why_an_undecodable_entry_will_not_decode(fake_redis):
    """The version-skew case: an ``event_type`` this co-core does not know."""
    frame = {**_observed_frame(), "event_type": "source_revision_observed_v9"}
    await fake_redis.xadd(ARTIFACTS_DLQ, frame)

    [entry], _ = await list_dead_letters(fake_redis, ARTIFACTS_DLQ, limit=10, offset=0)

    assert entry.decodes is False
    assert entry.event_type == "source_revision_observed_v9"
    assert "BusMessageUnknownEventTypeError" in entry.decode_error


async def test_list_tolerates_a_frame_with_no_event_type(fake_redis):
    await fake_redis.xadd(ARTIFACTS_DLQ, {"k": "v"})

    [entry], _ = await list_dead_letters(fake_redis, ARTIFACTS_DLQ, limit=10, offset=0)

    assert entry.event_type is None
    assert entry.decodes is False
    assert "BusMessageMissingFieldError" in entry.decode_error


async def test_list_of_an_absent_queue_is_empty(fake_redis):
    """A DLQ is created by its first quarantine, so absent means empty."""
    entries, has_more = await list_dead_letters(fake_redis, REVISIONS_DLQ, limit=10, offset=0)
    assert entries == []
    assert has_more is False


async def test_list_pages_oldest_first(fake_redis):
    ids = [(await fake_redis.xadd(REVISIONS_DLQ, {"n": str(n)})).decode() for n in range(5)]

    first, more_after_first = await list_dead_letters(fake_redis, REVISIONS_DLQ, limit=2, offset=0)
    last, more_after_last = await list_dead_letters(fake_redis, REVISIONS_DLQ, limit=2, offset=4)

    assert [e.entry_id for e in first] == ids[:2]
    assert more_after_first is True
    assert [e.entry_id for e in last] == ids[4:]
    assert more_after_last is False


async def test_list_clamps_the_xrange_count_at_int64(fake_redis):
    """``offset`` is bounded at int64 like every list route; ``offset + limit + 1``
    past that would be a COUNT redis refuses."""
    await fake_redis.xadd(REVISIONS_DLQ, {"n": "0"})

    entries, has_more = await list_dead_letters(
        fake_redis, REVISIONS_DLQ, limit=500, offset=2**63 - 1
    )

    assert entries == []
    assert has_more is False


# --- discarding ---


async def test_discard_deletes_only_the_named_entries(fake_redis):
    keep = (await fake_redis.xadd(REVISIONS_DLQ, {"n": "keep"})).decode()
    drop = (await fake_redis.xadd(REVISIONS_DLQ, {"n": "drop"})).decode()

    result = await discard_dead_letters(fake_redis, REVISIONS_DLQ, [drop])

    assert result.discarded == (drop,)
    assert result.not_found == ()
    assert [eid.decode() for eid, _ in await fake_redis.xrange(REVISIONS_DLQ)] == [keep]


async def test_discard_reports_ids_that_are_not_in_the_queue(fake_redis):
    present = (await fake_redis.xadd(REVISIONS_DLQ, {"n": "0"})).decode()

    result = await discard_dead_letters(fake_redis, REVISIONS_DLQ, ["1-0", present])

    assert result.discarded == (present,)
    assert result.not_found == ("1-0",)


async def test_discard_counts_a_repeated_id_once(fake_redis):
    entry_id = (await fake_redis.xadd(REVISIONS_DLQ, {"n": "0"})).decode()

    result = await discard_dead_letters(fake_redis, REVISIONS_DLQ, [entry_id, entry_id])

    assert result.discarded == (entry_id,)
    assert result.not_found == ()


UINT64_MAX = 2**64 - 1


@pytest.mark.parametrize("entry_id", ["0-0", "1726-0", f"{UINT64_MAX}-{UINT64_MAX}"])
def test_an_exact_stream_id_is_two_uint64_halves(entry_id):
    assert is_exact_stream_id(entry_id)


@pytest.mark.parametrize(
    "entry_id",
    [
        f"{UINT64_MAX + 1}-0",  # matches the digit pattern; Redis refuses the XRANGE
        f"0-{UINT64_MAX + 1}",
        "99999999999999999999999-0",
    ],
)
def test_a_half_past_uint64_is_not_a_stream_id(entry_id):
    """Redis parses each half as an unsigned 64-bit integer and answers
    ``ERR Invalid stream ID`` past it. fakeredis returns an empty range
    instead, so only this check can see the case."""
    assert not is_exact_stream_id(entry_id)


@pytest.mark.parametrize(
    "entry_id", ["-", "+", "1726", "not-an-id", "1726-0\n", f"{UINT64_MAX + 1}-0"]
)
async def test_discard_refuses_anything_but_an_exact_stream_id(fake_redis, entry_id):
    """``XRANGE`` reads ``-``/``+`` as the whole stream and a bare ``1726`` as a
    millisecond's worth of entries, so an inexact id is a wider read than the
    operator named. Refused before any command is sent."""
    await fake_redis.xadd(REVISIONS_DLQ, {"n": "0"}, id="1726-0")

    with pytest.raises(ValueError, match="stream id"):
        await discard_dead_letters(fake_redis, REVISIONS_DLQ, ["1726-0", entry_id])

    assert await fake_redis.xlen(REVISIONS_DLQ) == 1


async def test_discard_logs_each_frame_in_full_before_deleting_it(fake_redis):
    """The archiver-side record of what was destroyed. Broker's evidence capture
    runs on its own tick, so an entry discarded before the next one would
    otherwise leave nothing behind.

    Spies the module logger rather than using ``caplog``: another test in the
    suite runs ``configure_logging()``, after which ``caplog`` misses the record
    (the ``test_group_consumer`` precedent)."""
    frame = _observed_frame()
    entry_id = (await fake_redis.xadd(REVISIONS_DLQ, frame)).decode()
    order: list[str] = []
    real_xdel = fake_redis.xdel

    async def spy_xdel(*args):
        order.append("xdel")
        return await real_xdel(*args)

    with (
        patch.object(
            dlq_triage.logger, "info", side_effect=lambda *a, **k: order.append("log")
        ) as info,
        patch.object(fake_redis, "xdel", spy_xdel),
    ):
        await discard_dead_letters(fake_redis, REVISIONS_DLQ, [entry_id])

    assert order == ["log", "xdel"]
    [call] = info.call_args_list
    assert call.args == ("Discarding dead letter",)
    extra = call.kwargs["extra"]
    assert extra["dlq"] == REVISIONS_DLQ
    assert extra["entry_id"] == entry_id
    assert extra["fields"] == frame
