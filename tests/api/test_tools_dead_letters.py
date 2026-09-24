"""/tools/dead-letters/{dlq} - the operator's DLQ triage surface (archiver#238).

The route borrows the lifespan's Redis client through ``get_redis_client``; the
tests hand it a fakeredis instance, so XRANGE / XDEL run for real.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import ConnectionError as RedisConnectionError

from src.api.deps import get_redis_client
from src.api.main import app

HEADERS = {"X-API-Key": "test-secret-key"}
DLQ = "content.revisions.dlq"
LIST_URL = f"/api/v1/tools/dead-letters/{DLQ}"
DISCARD_URL = f"{LIST_URL}/discard"


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


async def test_discard_conflicts_when_bus_dormant(client):
    app.dependency_overrides[get_redis_client] = lambda: None
    resp = await client.post(DISCARD_URL, headers=HEADERS, json={"entry_ids": ["1-0"]})
    assert resp.status_code == 409


async def test_discard_requires_an_api_key(client, fake_redis):
    resp = await client.post(DISCARD_URL, json={"entry_ids": ["1-0"]})
    assert resp.status_code in (401, 403)
