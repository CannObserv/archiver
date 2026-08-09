"""End-to-end: POST /source-revisions → outbox → fakeredis stream.

Exercises the full path:
  HTTP POST /api/v1/info-items (with initial_url + initial_source_specs)
  → HTTP POST /api/v1/source-revisions
  → outbox row written transactionally in the same savepoint
  → drain_once publishes to fakeredis stream
  → outbox row marked as published with bus_message_id set
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.adapters.bus.streams import CONTENT_REVISIONS
from co_core.pure.models.changes import SourceRevisionObservedEvent
from co_core_aio.bus import AsyncBusPublisher
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes import consumer as revisions_consumer
from src.core.changes.publisher import drain_once
from src.core.models import ChangesOutboxRow, SourceRevision

pytestmark = pytest.mark.integration

HEADERS = {"X-API-Key": "test-secret-key"}

VALID_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}
VALID_URL = "https://example.com/integration-test"

FINGERPRINT = "sha256:" + "a" * 64


@pytest.fixture
async def fake_redis():
    """In-process FakeRedis async client with stream support."""
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture(autouse=True)
async def cleanup_outbox(test_engine):
    """Truncate outbox before and after each test so no cross-test leakage."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.changes_outbox"))


@pytest.mark.asyncio
async def test_source_revision_post_to_redis_stream(
    client,
    session,
    fake_redis,
):
    """Full path: HTTP POST → SourceRevision + outbox → drain → Redis stream."""
    # ------------------------------------------------------------------
    # Step 1: Create an InfoItem with an initial root InfoSource atomically.
    # ------------------------------------------------------------------
    create_resp = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "integration-test-item",
            "initial_url": VALID_URL,
            "initial_source_specs": [VALID_SPEC],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    info_item_id = body["info_item_id"]
    assert len(body["info_item_sources"]) == 1
    info_source_id = body["info_item_sources"][0]["info_source_id"]

    # ------------------------------------------------------------------
    # Step 2: POST a SourceRevision.
    # ------------------------------------------------------------------
    rev_resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": info_source_id,
            "content_fingerprint": FINGERPRINT,
            "captured_at": "2026-05-08T12:00:00Z",
            "content_size_bytes": 1234,
            "content_media_type": "text/html",
        },
    )
    assert rev_resp.status_code == 201, rev_resp.text
    source_revision_id = rev_resp.json()["source_revision_id"]

    # ------------------------------------------------------------------
    # Step 3: Verify outbox row written with correct payload.
    # ------------------------------------------------------------------
    outbox_result = await session.execute(
        select(ChangesOutboxRow).where(ChangesOutboxRow.published_at.is_(None))
    )
    outbox_rows = list(outbox_result.scalars())
    assert len(outbox_rows) == 1, f"Expected 1 outbox row, got {len(outbox_rows)}"
    outbox_row = outbox_rows[0]
    payload = outbox_row.payload
    assert payload["event_type"] == "source_revision_captured"
    assert payload["info_source_id"] == info_source_id
    assert payload["source_revision_id"] == source_revision_id
    assert payload["content_fingerprint"] == FINGERPRINT
    matching = [b for b in payload["bindings"] if b["info_item_id"] == info_item_id]
    assert matching, f"expected a binding for {info_item_id} in {payload['bindings']!r}"

    # ------------------------------------------------------------------
    # Step 4: Build a publisher session_factory bound to the SAME
    # connection that the test session uses.  This ensures drain_once
    # can see the savepoint-committed rows without a separate DB
    # connection.
    # ------------------------------------------------------------------
    conn = await session.connection()
    publisher_session_factory = async_sessionmaker(
        bind=conn,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    # ------------------------------------------------------------------
    # Step 5: Drain the outbox to fakeredis.
    # ------------------------------------------------------------------
    drained = await drain_once(
        session_factory=publisher_session_factory,
        publisher=AsyncBusPublisher(fake_redis),
    )
    assert drained == 1

    # ------------------------------------------------------------------
    # Step 6: Verify stream has 1 entry with matching payload.
    # ------------------------------------------------------------------
    entries = await fake_redis.xrange("info.changes")
    assert len(entries) == 1, f"Expected 1 stream entry, got {len(entries)}"
    _msg_id, fields = entries[0]
    raw_payload = fields.get(b"payload") or fields.get("payload")
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode()
    decoded = json.loads(raw_payload)
    assert decoded["info_source_id"] == info_source_id
    assert decoded["content_fingerprint"] == FINGERPRINT
    assert decoded["source_revision_id"] == source_revision_id

    # ------------------------------------------------------------------
    # Step 7: Verify outbox row marked as published.
    # ------------------------------------------------------------------
    session.expire(outbox_row)
    await session.refresh(outbox_row)
    assert outbox_row.published_at is not None, "outbox row.published_at should be set"
    assert outbox_row.bus_message_id is not None, "outbox row.bus_message_id should be set"


# ---------------------------------------------------------------------------
# Bus ingest: content.revisions → registry → info.changes (archiver#139)
# ---------------------------------------------------------------------------

OBSERVED_FINGERPRINT = "sha256:" + "b" * 64


@pytest.mark.asyncio
async def test_observed_event_to_redis_stream(client, session, fake_redis):
    """Full path: content.revisions fact → row → outbox → info.changes.

    The acceptance criterion of archiver#139. Nothing here talks HTTP except the
    fixture setup — the revision arrives as a bus fact and leaves as the same
    ``source_revision_captured`` event existing subscribers already consume.
    """
    create_resp = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "bus-ingest-item",
            "initial_url": "https://example.com/bus-ingest",
            "initial_source_specs": [VALID_SPEC],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    info_item_id = create_resp.json()["info_item_id"]
    info_source_id = create_resp.json()["info_item_sources"][0]["info_source_id"]

    observed = SourceRevisionObservedEvent(
        occurred_at=datetime.now(UTC),
        info_source_id=info_source_id,
        extracted_fingerprint=OBSERVED_FINGERPRINT,
        captured_at=datetime(2026, 8, 9, 10, 0, tzinfo=UTC),
        content_size_bytes=512,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="file:///var/lib/replicator/blobs/aa/bb/cafe.bin",
        blob_expires_at=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
        command_id="cmd-e2e",
        spec_fingerprint="sha256:" + "c" * 64,
    )
    await fake_redis.xadd(CONTENT_REVISIONS, to_wire(observed))

    # The consumer opens its own sessions; bind them to this test's connection
    # so it sees the savepoint-committed InfoSource and the test sees its writes.
    conn = await session.connection()
    ingest_session_factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    bus_consumer = revisions_consumer.build_consumer(fake_redis, consumer_name="e2e:1")
    await revisions_consumer.ensure_group(bus_consumer)

    processed = await revisions_consumer.consume_once(
        session_factory=ingest_session_factory, consumer=bus_consumer
    )
    assert processed == 1

    rev = (
        await session.execute(
            select(SourceRevision).where(SourceRevision.content_fingerprint == OBSERVED_FINGERPRINT)
        )
    ).scalar_one()
    assert rev.content_cache_uri == "file:///var/lib/replicator/blobs/aa/bb/cafe.bin"
    assert rev.source_media_type == "text/html"

    drained = await drain_once(
        session_factory=ingest_session_factory, publisher=AsyncBusPublisher(fake_redis)
    )
    assert drained == 1

    entries = await fake_redis.xrange("info.changes")
    assert len(entries) == 1
    _msg_id, fields = entries[0]
    assert fields[b"event_type"] == b"source_revision_captured"
    # The envelope key is the registry's, not the observation's — this event is
    # Archiver's own fact, keyed as it always was.
    assert fields[b"key"] == str(rev.source_revision_id).encode()
    decoded = json.loads(fields[b"payload"].decode())
    assert decoded["info_source_id"] == info_source_id
    assert decoded["source_revision_id"] == str(rev.source_revision_id)
    assert decoded["content_fingerprint"] == OBSERVED_FINGERPRINT
    assert [b["info_item_id"] for b in decoded["bindings"]] == [info_item_id]


@pytest.mark.asyncio
async def test_bus_and_http_payloads_are_identical(client, session, fake_redis):
    """The two ingest paths emit the same event, field for field.

    "Byte-identical payloads" is the issue's acceptance bar. Both paths call
    record_revision, so this asserts the extraction actually holds rather than
    re-deriving the shape.
    """
    create_resp = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "parity-item",
            "initial_url": "https://example.com/parity",
            "initial_source_specs": [VALID_SPEC],
        },
    )
    info_source_id = create_resp.json()["info_item_sources"][0]["info_source_id"]
    captured_at = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)

    http_resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={
            "info_source_id": info_source_id,
            "content_fingerprint": "sha256:" + "d" * 64,
            "captured_at": captured_at.isoformat(),
            "content_size_bytes": 512,
            "content_media_type": "text/plain",
        },
    )
    assert http_resp.status_code == 201, http_resp.text

    observed = SourceRevisionObservedEvent(
        occurred_at=datetime.now(UTC),
        info_source_id=info_source_id,
        extracted_fingerprint="sha256:" + "e" * 64,
        captured_at=captured_at,
        content_size_bytes=512,
        content_media_type="text/plain",
        source_media_type="text/html",
        blob_uri="file:///var/lib/replicator/blobs/aa/bb/beef.bin",
    )
    await fake_redis.xadd(CONTENT_REVISIONS, to_wire(observed))
    conn = await session.connection()
    ingest_session_factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    bus_consumer = revisions_consumer.build_consumer(fake_redis, consumer_name="parity:1")
    await revisions_consumer.ensure_group(bus_consumer)
    assert (
        await revisions_consumer.consume_once(
            session_factory=ingest_session_factory, consumer=bus_consumer
        )
        == 1
    )

    rows = (
        (await session.execute(select(ChangesOutboxRow).order_by(ChangesOutboxRow.created_at)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    http_payload, bus_payload = rows[0].payload, rows[1].payload

    assert rows[0].topic == rows[1].topic == "info.changes"
    assert http_payload.keys() == bus_payload.keys()
    # Everything but the identifiers and the emit timestamp is the same event.
    variable = {"source_revision_id", "content_fingerprint", "occurred_at"}
    assert {k: v for k, v in http_payload.items() if k not in variable} == {
        k: v for k, v in bus_payload.items() if k not in variable
    }
