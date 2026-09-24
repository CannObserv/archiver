"""/tools/outbox/dead-lettered - the operator's outbox triage surface (archiver#191).

The routes run on the request's DB session; the ``client`` fixture hands them
the SAVEPOINT-scoped ``session``, so every row here rolls back with the test.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import ChangesOutboxRow

HEADERS = {"X-API-Key": "test-secret-key"}
LIST_URL = "/api/v1/tools/outbox/dead-lettered"
DISCARD_URL = f"{LIST_URL}/discard"
REARM_URL = f"{LIST_URL}/rearm"

_T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _captured_event() -> dict:
    """A full, publishable ``source_revision_captured`` payload."""
    return {
        "schema_version": 2,
        "event_type": "source_revision_captured",
        "occurred_at": "2026-07-28T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": "rev-1",
        "content_fingerprint": "sha256:" + "a" * 64,
        "bindings": [{"info_item_id": "01HZZ000000000000000000003"}],
    }


async def _dead_lettered(session, *, topic="info.changes", payload=None) -> ChangesOutboxRow:
    row = ChangesOutboxRow(
        topic=topic,
        payload=payload if payload is not None else _captured_event(),
        dead_lettered_at=_T0,
        publish_attempts=100_000,
        last_error="WRONGTYPE Operation against a key holding the wrong kind",
    )
    session.add(row)
    await session.flush()
    return row


# --- listing ---


async def test_list_returns_dead_lettered_rows(client, session):
    row = await _dead_lettered(session)
    session.add(ChangesOutboxRow(topic="info.changes", payload=_captured_event()))  # live
    await session.flush()

    resp = await client.get(LIST_URL, headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 100 and body["offset"] == 0
    [item] = [i for i in body["items"] if i["row_id"] == str(row.id)]
    assert item["topic"] == "info.changes"
    assert item["event_type"] == "source_revision_captured"
    assert item["payload"] == _captured_event()
    assert item["last_error"].startswith("WRONGTYPE")
    assert item["publish_attempts"] == 100_000
    assert item["dead_lettered_at"].endswith("Z")
    assert item["rearmable"] is True
    assert all(i["dead_lettered_at"] is not None for i in body["items"])


async def test_list_marks_refused_topics_not_rearmable(client, session):
    row = await _dead_lettered(session, topic="info.registry")
    body = (await client.get(LIST_URL, headers=HEADERS)).json()
    [item] = [i for i in body["items"] if i["row_id"] == str(row.id)]
    assert item["rearmable"] is False


async def test_list_shows_a_non_object_payload_as_stored(client, session):
    """The publisher dead-letters a non-dict payload too; the triage listing is
    where an operator reads it, so it must not be flattened to ``{}``."""
    row = await _dead_lettered(session, payload=["not", "an", "object"])
    body = (await client.get(LIST_URL, headers=HEADERS)).json()
    [item] = [i for i in body["items"] if i["row_id"] == str(row.id)]
    assert item["payload"] == ["not", "an", "object"]
    assert item["event_type"] is None


async def test_list_over_max_limit_is_a_422(client):
    resp = await client.get(LIST_URL, params={"limit": 501}, headers=HEADERS)
    assert resp.status_code == 422


# --- discard ---


async def test_discard_deletes_named_rows_and_reports_the_rest(client, session):
    row = await _dead_lettered(session)
    missing = str(ULID())

    resp = await client.post(DISCARD_URL, json={"row_ids": [str(row.id), missing]}, headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json() == {"discarded": [str(row.id)], "not_found": [missing]}
    gone = await session.execute(select(ChangesOutboxRow).where(ChangesOutboxRow.id == row.id))
    assert gone.scalar_one_or_none() is None


@pytest.mark.parametrize(
    "body",
    [{"row_ids": []}, {"row_ids": ["not-a-ulid"]}, {"row_ids": [str(ULID())] * 501}, {}],
)
async def test_discard_refuses_a_malformed_body(client, body):
    resp = await client.post(DISCARD_URL, json=body, headers=HEADERS)
    assert resp.status_code == 422


# --- rearm ---


async def test_rearm_reports_one_outcome_per_row(client, session):
    ok = await _dead_lettered(session)
    registry = await _dead_lettered(session, topic="info.registry")
    poison = await _dead_lettered(session, payload={"event_type": "who_knows"})
    missing = str(ULID())

    resp = await client.post(
        REARM_URL,
        json={"row_ids": [str(ok.id), str(registry.id), str(poison.id), missing]},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    outcomes = [(r["row_id"], r["outcome"]) for r in resp.json()["results"]]
    assert outcomes == [
        (str(ok.id), "rearmed"),
        (str(registry.id), "refused"),
        (str(poison.id), "rejected"),
        (missing, "not_found"),
    ]
    await session.refresh(ok)
    assert ok.dead_lettered_at is None
    assert ok.publish_attempts == 0


async def test_rearm_refuses_a_malformed_body(client):
    resp = await client.post(REARM_URL, json={"row_ids": ["nope"]}, headers=HEADERS)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("method", "url"), [("get", LIST_URL), ("post", DISCARD_URL), ("post", REARM_URL)]
)
async def test_routes_require_an_api_key(client, method, url):
    resp = await getattr(client, method)(url)
    assert resp.status_code in (401, 403)
