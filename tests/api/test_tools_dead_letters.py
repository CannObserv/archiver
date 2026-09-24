"""/tools/dead-letters/{dlq} - the operator's DLQ triage surface (archiver#238).

The route borrows the lifespan's Redis client through ``get_redis_client``; the
tests hand it a fakeredis instance, so XRANGE / XDEL run for real.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from co_core.pure.adapters.bus.dead_letter import dead_letter_fields
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.api.deps import get_db_session_factory, get_redis_client
from src.api.main import app

HEADERS = {"X-API-Key": "test-secret-key"}
DLQ = "content.revisions.dlq"
LIST_URL = f"/api/v1/tools/dead-letters/{DLQ}"
DISCARD_URL = f"{LIST_URL}/discard"
REPROCESS_URL = f"{LIST_URL}/reprocess"


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    app.dependency_overrides[get_redis_client] = lambda: r
    yield r
    await r.aclose()


# --- listing ---


async def test_list_returns_a_page_of_entries(client, fake_redis):
    entry_id = (await fake_redis.xadd(DLQ, {"event_type": "nope", "payload": "{}"})).decode()

    resp = await client.get(LIST_URL, headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["has_more"] is False
    assert body["limit"] == 100
    assert body["offset"] == 0
    [item] = body["items"]
    assert item["entry_id"] == entry_id
    assert item["fields"] == {"event_type": "nope", "payload": "{}"}
    assert item["event_type"] == "nope"
    assert item["decodes"] is False
    assert "BusMessageUnknownEventTypeError" in item["decode_error"]
    assert item["dead_lettered_at"].endswith("Z")


async def test_list_returns_each_entrys_provenance(client, fake_redis):
    fields = dead_letter_fields(
        {"event_type": "nope", "payload": "{}"},
        source_id="1727179200000-0",
        group="archiver.revisions",
        consumer="archiver-revisions-1",
        reason="undecodable: BusMessageUnknownEventTypeError('nope')",
    )
    await fake_redis.xadd(DLQ, fields)

    [item] = (await client.get(LIST_URL, headers=HEADERS)).json()["items"]

    assert item["provenance"] == {
        "source_id": "1727179200000-0",
        "group": "archiver.revisions",
        "consumer": "archiver-revisions-1",
        "reason": "undecodable: BusMessageUnknownEventTypeError('nope')",
    }
    assert item["parked_as"] == "undecodable"
    assert item["owned"] is True


async def test_list_pages_with_limit_and_offset(client, fake_redis):
    for n in range(3):
        await fake_redis.xadd(DLQ, {"n": str(n)})

    resp = await client.get(f"{LIST_URL}?limit=2&offset=1", headers=HEADERS)

    body = resp.json()
    assert [item["fields"]["n"] for item in body["items"]] == ["1", "2"]
    assert body["has_more"] is False


async def test_list_limit_over_max_is_a_422(client, fake_redis):
    resp = await client.get(f"{LIST_URL}?limit=501", headers=HEADERS)
    assert resp.status_code == 422


async def test_list_offset_at_int64_max_is_accepted(client, fake_redis):
    resp = await client.get(f"{LIST_URL}?offset={2**63 - 1}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.parametrize(
    "dlq",
    [
        "content.fetch.dlq",  # replicator's to triage, not archiver's
        "content.revisions",  # the stream the queue copies
    ],
)
async def test_a_queue_outside_the_allowlist_is_a_422(client, fake_redis, dlq):
    resp = await client.get(f"/api/v1/tools/dead-letters/{dlq}", headers=HEADERS)
    assert resp.status_code == 422


async def test_list_conflicts_when_bus_dormant(client):
    app.dependency_overrides[get_redis_client] = lambda: None
    resp = await client.get(LIST_URL, headers=HEADERS)
    assert resp.status_code == 409
    assert resp.json()["detail"]["kind"] == "conflict"


async def test_a_broker_failure_is_a_503(client):
    """Distinct from an empty queue: "could not read" must not look like 0."""
    broken = MagicMock()
    broken.xrange = AsyncMock(side_effect=RedisConnectionError("broker unreachable"))
    app.dependency_overrides[get_redis_client] = lambda: broken

    resp = await client.get(LIST_URL, headers=HEADERS)

    assert resp.status_code == 503
    assert resp.json()["detail"]["kind"] == "server"


async def test_list_requires_an_api_key(client, fake_redis):
    resp = await client.get(LIST_URL)
    assert resp.status_code in (401, 403)


# --- discarding ---


async def test_discard_deletes_the_named_entries(client, fake_redis):
    keep = (await fake_redis.xadd(DLQ, {"n": "keep"})).decode()
    drop = (await fake_redis.xadd(DLQ, {"n": "drop"})).decode()

    resp = await client.post(DISCARD_URL, headers=HEADERS, json={"entry_ids": [drop, "1-0"]})

    assert resp.status_code == 200
    assert resp.json() == {"discarded": [drop], "not_found": ["1-0"]}
    assert [eid.decode() for eid, _ in await fake_redis.xrange(DLQ)] == [keep]


@pytest.mark.parametrize(
    "entry_ids",
    [
        [],  # a no-op request is a caller bug
        ["not-an-id"],
        ["1726"],  # XRANGE would read this as a range start, not one entry
        ["-", "+"],  # XRANGE's range sentinels: every entry
        # A half past uint64 matches the digit pattern and Redis refuses it -
        # mid-loop, after the valid id before it was already deleted.
        ["1726-0", f"{2**64}-0"],
    ],
)
async def test_discard_rejects_ids_that_are_not_exact_stream_ids(client, fake_redis, entry_ids):
    await fake_redis.xadd(DLQ, {"n": "0"}, id="1726-0")

    resp = await client.post(DISCARD_URL, headers=HEADERS, json={"entry_ids": entry_ids})

    assert resp.status_code == 422
    assert await fake_redis.xlen(DLQ) == 1


async def test_discard_from_a_queue_outside_the_allowlist_is_a_422(client, fake_redis):
    entry_id = (await fake_redis.xadd("content.revisions", {"n": "0"})).decode()

    resp = await client.post(
        "/api/v1/tools/dead-letters/content.revisions/discard",
        headers=HEADERS,
        json={"entry_ids": [entry_id]},
    )

    assert resp.status_code == 422
    assert await fake_redis.xlen("content.revisions") == 1


async def test_a_broker_failure_mid_discard_is_a_503_that_names_its_progress(client, fake_redis):
    """Without ``data``, a retry would report the ids this request already deleted
    as not_found - indistinguishable from ids that never existed."""
    first, second = [(await fake_redis.xadd(DLQ, {"n": str(n)})).decode() for n in range(2)]
    real_xdel = fake_redis.xdel
    calls = 0

    async def xdel_then_fail(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RedisConnectionError("broker went away")
        return await real_xdel(*args)

    with patch.object(fake_redis, "xdel", xdel_then_fail):
        resp = await client.post(DISCARD_URL, headers=HEADERS, json={"entry_ids": [first, second]})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["kind"] == "server"
    assert detail["data"] == {"discarded": [first], "not_found": [], "in_doubt": second}


async def test_discard_conflicts_when_bus_dormant(client):
    app.dependency_overrides[get_redis_client] = lambda: None
    resp = await client.post(DISCARD_URL, headers=HEADERS, json={"entry_ids": ["1-0"]})
    assert resp.status_code == 409


async def test_discard_requires_an_api_key(client, fake_redis):
    resp = await client.post(DISCARD_URL, json={"entry_ids": ["1-0"]})
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/tools/dead-letters/{dlq}", "get"),
        ("/api/v1/tools/dead-letters/{dlq}/discard", "post"),
        ("/api/v1/tools/dead-letters/{dlq}/reprocess", "post"),
    ],
)
def test_openapi_names_the_queues_the_dlq_parameter_accepts(path, method):
    """An SDK caller should learn the two legal values from the contract, not a 422."""
    params = app.openapi()["paths"][path][method]["parameters"]
    [dlq] = [p for p in params if p["name"] == "dlq"]
    assert "content.revisions.dlq" in dlq["description"]
    assert "content.artifacts.dlq" in dlq["description"]


# --- reprocessing ---


def _observed_wire(info_source_id: str, fingerprint: str = "sha256:" + "c" * 64) -> dict[str, str]:
    return to_wire(
        SourceRevisionObservedEvent(
            occurred_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            info_source_id=info_source_id,
            extracted_fingerprint=fingerprint,
            captured_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
            content_size_bytes=10,
            content_media_type="text/plain",
            source_media_type="text/html",
            blob_uri="file:///blob",
            command_id="cmd-route",
        )
    )


async def _park_owned(fake_redis, frame: dict[str, str], source_id: str = "9-0") -> str:
    fields = dead_letter_fields(
        frame,
        source_id=source_id,
        group="archiver.revisions",
        consumer="archiver-revisions-1",
        reason="undecodable: BusMessageUnknownEventTypeError('source_revision_observed')",
    )
    return (await fake_redis.xadd(DLQ, fields)).decode()


@pytest.fixture
def db_factory(test_engine):
    """The route's handlers open their own sessions, as the consumer loop does."""
    app.dependency_overrides[get_db_session_factory] = lambda: async_sessionmaker(
        bind=test_engine, expire_on_commit=False
    )
    yield


async def test_reprocess_runs_the_handler_and_removes_what_it_settled(
    client, fake_redis, db_factory
):
    """An observation for an InfoSource the registry does not hold is the handler's
    ack-and-drop: settled, so the entry goes. Poison stays for a discard."""
    dropped = await _park_owned(fake_redis, _observed_wire(str(ULID())), source_id="1-0")
    poison = await _park_owned(
        fake_redis, _observed_wire(str(ULID()), fingerprint="deadbeef"), source_id="2-0"
    )

    resp = await client.post(REPROCESS_URL, headers=HEADERS, json={"entry_ids": [dropped, poison]})

    assert resp.status_code == 200
    [first, second] = resp.json()["results"]
    assert first == {"entry_id": dropped, "outcome": "reprocessed", "detail": None}
    assert second["entry_id"] == poison
    assert second["outcome"] == "rejected"
    assert "InvalidFingerprintError" in second["detail"]
    assert [eid.decode() for eid, _ in await fake_redis.xrange(DLQ)] == [poison]


async def test_reprocess_rejects_inexact_ids(client, fake_redis, db_factory):
    resp = await client.post(REPROCESS_URL, headers=HEADERS, json={"entry_ids": ["-"]})
    assert resp.status_code == 422


async def test_reprocess_outside_the_allowlist_is_a_422(client, fake_redis, db_factory):
    resp = await client.post(
        "/api/v1/tools/dead-letters/content.fetch.dlq/reprocess",
        headers=HEADERS,
        json={"entry_ids": ["1-0"]},
    )
    assert resp.status_code == 422


async def test_reprocess_conflicts_when_bus_dormant(client, db_factory):
    app.dependency_overrides[get_redis_client] = lambda: None
    resp = await client.post(REPROCESS_URL, headers=HEADERS, json={"entry_ids": ["1-0"]})
    assert resp.status_code == 409


async def test_a_broker_failure_mid_reprocess_is_a_503_that_names_its_progress(
    client, fake_redis, db_factory
):
    first = await _park_owned(fake_redis, _observed_wire(str(ULID())), source_id="1-0")
    second = await _park_owned(fake_redis, _observed_wire(str(ULID())), source_id="2-0")
    real_xdel = fake_redis.xdel
    calls = 0

    async def xdel_then_fail(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RedisConnectionError("broker went away")
        return await real_xdel(*args)

    with patch.object(fake_redis, "xdel", xdel_then_fail):
        resp = await client.post(
            REPROCESS_URL, headers=HEADERS, json={"entry_ids": [first, second]}
        )

    assert resp.status_code == 503
    assert resp.json()["detail"]["data"] == {
        "results": [{"entry_id": first, "outcome": "reprocessed", "detail": None}],
        "in_doubt": second,
    }


async def test_reprocess_requires_an_api_key(client, fake_redis):
    resp = await client.post(REPROCESS_URL, json={"entry_ids": ["1-0"]})
    assert resp.status_code in (401, 403)
