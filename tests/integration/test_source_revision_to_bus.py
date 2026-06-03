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

import pytest
from fakeredis import aioredis as fakeredis_aio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.changes.publisher import drain_once
from src.core.models import ChangesOutboxRow

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
        redis=fake_redis,
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
