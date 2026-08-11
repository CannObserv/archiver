"""``DELETE /info-items/{id}`` — the registry's only exit for an InfoItem.

Filed under archiver#141. Before this route the registry had **no way to delete
an InfoItem**: the two existing ``@router.delete`` routes are sub-resources (a
source binding, a rep-spec assignment). The only exit was raw SQL — and raw SQL
cannot write a ``changes_outbox`` row in the same transaction, so once the
producer lands, a psql deletion silently skips its ``revoked`` tombstone and
every consumer keeps the key forever. The snapshot does not correct it:
``revoked`` is an explicit tombstone precisely because absence-from-a-full-set
is *not* the delete signal in this design.

So the route exists to give the tombstone a transactional home. It emits nothing
yet — the announcement service does not exist — but the emit site does, and the
alternative (declaring InfoItems undeletable in docs/SCHEMA.md) does not actually
stop anyone from reaching for psql.

**Scope of the cascade is deliberate.** The item's own bindings and rep-spec
assignments go with it (both FKs are ``ondelete="CASCADE"``). The InfoSource and
its SourceRevisions do not: the physical layer is shared, ``source_revisions``
keys on ``info_source_id``, and its ``RESTRICT`` never sees an item delete.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from ulid import ULID

import src.api.routes.info_items as info_items_routes
from src.core.models import InfoItem, InfoItemRepSpec, RepSpec, SourceRevision

HEADERS = {"X-API-Key": "test-secret-key"}


def _source_payload(url: str = "https://example.com") -> dict:
    return {
        "url": url,
        "source_specs": [
            {
                "schema_version": 1,
                "extraction": {"algorithm": "css", "selector": "body"},
                "fingerprint": {},
            }
        ],
    }


async def _make_item(client, name: str = "Item") -> str:
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["info_item_id"]


async def _make_source(client, url: str = "https://example.com") -> str:
    resp = await client.post("/api/v1/info-sources", headers=HEADERS, json=_source_payload(url))
    assert resp.status_code == 201, resp.text
    return resp.json()["info_source_id"]


async def _bind(client, item_id: str, source_id: str) -> None:
    resp = await client.post(
        f"/api/v1/info-items/{item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": source_id},
    )
    assert resp.status_code == 201, resp.text


async def _count_bindings(session, item_id: str) -> int:
    """Row count straight from SQL — the cascade is a database rule, so the
    assertion has to reach the database to mean anything."""
    return (
        await session.execute(
            text("select count(*) from information.info_item_sources where info_item_id = :i"),
            {"i": item_id},
        )
    ).scalar_one()


async def _count_rep_spec_assignments(session, item_id: str) -> int:
    return (
        await session.execute(
            text("select count(*) from information.info_item_rep_specs where info_item_id = :i"),
            {"i": item_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_delete_removes_the_item(client):
    item_id = await _make_item(client)

    response = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert response.status_code == 204
    assert response.content == b""

    assert (await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)).status_code == 404


@pytest.mark.asyncio
async def test_delete_cascades_the_item_s_bindings(client, session):
    """A bound item deletes cleanly; the binding goes with it."""
    item_id = await _make_item(client)
    source_id = await _make_source(client)
    await _bind(client, item_id, source_id)

    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    # Count in SQL rather than session.get: the fixture shares one session with the
    # app under expire_on_commit=False, so an ORM lookup can answer from the
    # identity map and never reach the database-level cascade (CR round 1, #7).
    assert await _count_bindings(session, item_id) == 0


@pytest.mark.asyncio
async def test_delete_cascades_the_item_s_rep_spec_assignments(client, session):
    """The assignment goes; the RepSpec itself does not — it is reusable across
    items, and its ``document`` is frozen once assigned."""
    item_id = await _make_item(client)
    rep_spec = RepSpec(
        provider="gcs",
        name="test-rep-delete",
        schema_version=1,
        document={
            "schema_version": 1,
            "provider": "gcs",
            "credentials_alias": "default",
            "path_template": "gs://bucket/{info_item_id}",
            "required_fields": [],
        },
    )
    session.add(rep_spec)
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=ULID.from_str(item_id),
        rep_spec_id=rep_spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.commit()

    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    assert await _count_rep_spec_assignments(session, item_id) == 0
    # The RepSpec itself survives — reusable across items, document frozen once
    # assigned. Expunge first so this reads the database, not the identity map.
    session.expunge_all()
    assert await session.get(RepSpec, rep_spec.rep_spec_id) is not None


@pytest.mark.asyncio
async def test_delete_leaves_the_shared_physical_layer_intact(client, session):
    """The InfoSource and its SourceRevisions survive — they are not the item's.

    An InfoSource can be the active primary for several InfoItems, and a
    SourceRevision is a content-addressed snapshot of a URL, not of an item.
    Cascading into either would destroy another item's primary and discard
    archived content on an unrelated delete.
    """
    item_id = await _make_item(client)
    source_id = await _make_source(client)
    await _bind(client, item_id, source_id)

    revision = SourceRevision(
        info_source_id=ULID.from_str(source_id),
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    session.add(revision)
    await session.commit()

    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    source = await client.get(f"/api/v1/info-sources/{source_id}", headers=HEADERS)
    assert source.status_code == 200
    assert await session.get(SourceRevision, revision.source_revision_id) is not None


@pytest.mark.asyncio
async def test_delete_is_not_idempotent_on_a_missing_item(client):
    """404 rather than a silent 204 — an operator deleting the wrong ULID twice
    should learn the second one did nothing."""
    item_id = await _make_item(client)
    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    repeat = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert repeat.status_code == 404
    assert repeat.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
async def test_delete_rejects_a_malformed_ulid(client):
    response = await client.delete("/api/v1/info-items/not-a-ulid", headers=HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_without_a_key_is_403_not_401(client, session):
    """Absent header is 403, unmatched key is 401 — the two are not interchangeable.

    ``require_api_key`` is deterministic about which it raises, and SDK consumers
    switch on the status, so a swapped pair is a contract change. Pinning both
    branches is what makes that visible (CR round 1, finding 3).
    """
    item_id = await _make_item(client)

    response = await client.delete(f"/api/v1/info-items/{item_id}")
    assert response.status_code == 403

    assert await session.get(InfoItem, ULID.from_str(item_id)) is not None


@pytest.mark.asyncio
async def test_delete_with_an_unknown_api_key_is_401(client, session):
    item_id = await _make_item(client)

    response = await client.delete(
        f"/api/v1/info-items/{item_id}", headers={"X-API-Key": "not-a-real-key"}
    )
    assert response.status_code == 401

    assert await session.get(InfoItem, ULID.from_str(item_id)) is not None


@pytest.mark.asyncio
async def test_delete_warns_when_the_item_still_has_a_watcher_link(client, session, monkeypatch):
    """An orphaned WatchedItem gets a log line, not just a docs paragraph.

    Nothing tells Watcher until watcher#254 consumes tombstones, so the deleted
    item's WatchedItem keeps fetching until someone removes it by hand. Prose in
    SCHEMA.md is the right *record* of an accepted gap; it is not a signal the
    operator who caused it will see (CR round 1, finding 2).

    Spies the module logger rather than using caplog — ``configure_logging()``
    replaces ``root.handlers``, which defeats pytest's capture handler. Same
    reason as ``tests/core/test_watcher_provisioning.py``.
    """
    item_id = await _make_item(client)
    item = await session.get(InfoItem, ULID.from_str(item_id))
    item.watcher_item_id = "watched-123"
    await session.commit()

    spy = MagicMock()
    monkeypatch.setattr(info_items_routes.logger, "warning", spy)

    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    spy.assert_called_once()
    assert spy.call_args.kwargs["extra"]["watcher_item_id"] == "watched-123"
    assert spy.call_args.kwargs["extra"]["info_item_id"] == item_id


@pytest.mark.asyncio
async def test_delete_of_an_unwatched_item_is_quiet(client, monkeypatch):
    """No warning when there is no orphan — otherwise the signal is noise."""
    item_id = await _make_item(client)

    spy = MagicMock()
    monkeypatch.setattr(info_items_routes.logger, "warning", spy)

    deleted = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert deleted.status_code == 204

    spy.assert_not_called()
