"""InfoItem tags over the API (archiver#362, D3).

``InfoItemOut`` carries ``tags``; ``PUT /info-items/{id}/tags`` replaces the
whole set and answers with the item. D2's rule refuses with a 422 naming each
tag by its JSON-pointer path. Nothing announces: tags never go on the bus.
"""

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import ChangesOutboxRow

HEADERS = {"X-API-Key": "test-secret-key"}

_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "body"},
    "fingerprint": {},
}


async def _make_item(client) -> str:
    body = {
        "name": "Tagged",
        "initial_url": "https://tags.example.com/a",
        "initial_source_specs": [_SPEC],
    }
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["info_item_id"]


def _url(item_id: str) -> str:
    return f"/api/v1/info-items/{item_id}/tags"


async def _outbox(session) -> int:
    return (await session.execute(select(func.count()).select_from(ChangesOutboxRow))).scalar()


@pytest.mark.asyncio
async def test_a_new_item_has_no_tags(client):
    item_id = await _make_item(client)

    resp = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)

    assert resp.json()["tags"] == []


@pytest.mark.asyncio
async def test_put_replaces_the_whole_set_stored_sorted(client):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json={"tags": ["old", "keep"]})

    resp = await client.put(
        _url(item_id), headers=HEADERS, json={"tags": [" zeta", "keep", "Alpha", "keep"]}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["tags"] == ["Alpha", "keep", "zeta"]
    got = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert got.json()["tags"] == ["Alpha", "keep", "zeta"]


@pytest.mark.asyncio
async def test_put_of_the_empty_list_clears_the_tags(client):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json={"tags": ["a"]})

    resp = await client.put(_url(item_id), headers=HEADERS, json={"tags": []})

    assert resp.json()["tags"] == []


@pytest.mark.asyncio
async def test_a_tag_breaking_the_rule_is_a_422_naming_each_and_stores_nothing(client):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json={"tags": ["kept"]})

    resp = await client.put(
        _url(item_id), headers=HEADERS, json={"tags": ["ok", "", "a,b", "x" * 256]}
    )

    assert resp.status_code == 422
    body = resp.json()["detail"]
    assert [e["path"] for e in body["errors"]] == ["/tags/1", "/tags/2", "/tags/3"]
    got = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert got.json()["tags"] == ["kept"]


@pytest.mark.asyncio
async def test_more_than_32_tags_is_a_422_on_the_set(client):
    item_id = await _make_item(client)

    resp = await client.put(
        _url(item_id), headers=HEADERS, json={"tags": [f"t{n}" for n in range(33)]}
    )

    assert resp.status_code == 422
    assert [e["path"] for e in resp.json()["detail"]["errors"]] == ["/tags"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"tags": "a"}, {"tags": [1]}, {"tags": [], "extra": 1}])
async def test_a_malformed_body_is_a_422(client, body):
    item_id = await _make_item(client)

    resp = await client.put(_url(item_id), headers=HEADERS, json=body)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_on_a_missing_item_is_a_404(client):
    resp = await client.put(_url(str(ULID())), headers=HEADERS, json={"tags": ["a"]})

    assert resp.status_code == 404
    assert resp.json()["detail"]["kind"] == "lookup"


@pytest.mark.asyncio
async def test_put_needs_an_api_key(client):
    item_id = await _make_item(client)

    resp = await client.put(_url(item_id), json={"tags": ["a"]})

    assert resp.status_code == 403
    assert resp.json()["detail"]["kind"] == "auth"


@pytest.mark.asyncio
async def test_tags_are_allowed_on_an_archived_item(client):
    item_id = await _make_item(client)
    await client.post(f"/api/v1/info-items/{item_id}/archive", headers=HEADERS)

    resp = await client.put(_url(item_id), headers=HEADERS, json={"tags": ["a"]})

    assert resp.status_code == 200
    assert resp.json()["tags"] == ["a"]


@pytest.mark.asyncio
async def test_a_tag_write_announces_nothing(client, session):
    item_id = await _make_item(client)
    before = await _outbox(session)

    await client.put(_url(item_id), headers=HEADERS, json={"tags": ["a"]})

    assert await _outbox(session) == before
