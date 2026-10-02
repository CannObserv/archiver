"""PUT /info-items/{id}/rep-fields — the validated bag write (archiver#302).

The only route that changes a bag after create. Checks the v1 shape, every
active assignment, and whether a valid edit moves an assignment's destination.
"""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec

HEADERS = {"X-API-Key": "test-secret-key"}

_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"


async def _assigned(session, bag: dict, *specs: RepSpec) -> InfoItem:
    item = InfoItem(name="bagged", rep_fields=bag)
    session.add(item)
    session.add_all(specs)
    await session.flush()
    for spec in specs:
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
    await session.flush()
    return item


def _spec(name: str, *required: str, path_template: str = _ORG_PATH) -> RepSpec:
    return RepSpec(
        provider="gcs",
        name=name,
        schema_version=1,
        document={"required_fields": list(required), "path_template": path_template},
    )


def _url(item: InfoItem | str) -> str:
    item_id = item if isinstance(item, str) else item.info_item_id
    return f"/api/v1/info-items/{item_id}/rep-fields"


@pytest.mark.asyncio
async def test_put_replaces_the_whole_bag_and_returns_the_item(client, session):
    item = await _assigned(session, {"org": {"title": "WA LCB"}, "info_item": {"name": "N"}})

    response = await client.put(
        _url(item), headers=HEADERS, json={"rep_fields": {"org": {"acronym": "WSLCB"}}}
    )

    assert response.status_code == 200, response.text
    assert response.json()["rep_fields"] == {"org": {"acronym": "WSLCB"}}
    await session.refresh(item)
    assert item.rep_fields == {"org": {"acronym": "WSLCB"}}


@pytest.mark.asyncio
async def test_put_requires_an_api_key(client, session):
    item = await _assigned(session, {})
    response = await client.put(_url(item), json={"rep_fields": {}})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_unknown_item_is_404(client):
    response = await client.put(_url(str(ULID())), headers=HEADERS, json={"rep_fields": {}})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_put_refuses_unknown_body_fields(client, session):
    item = await _assigned(session, {})
    response = await client.put(_url(item), headers=HEADERS, json={"rep_fields": {}, "merge": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_refuses_a_bag_off_the_v1_shape(client, session):
    item = await _assigned(session, {"org": {"title": "WA LCB"}})

    response = await client.put(_url(item), headers=HEADERS, json={"rep_fields": {"flat": "x"}})

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("/rep_fields/flat", "rep_fields_invalid")]
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_put_refusal_names_the_assignment_and_the_key(client, session):
    spec = _spec("Org spec", "org.title_slug")
    item = await _assigned(session, {"org": {"title": "WA LCB"}}, spec)

    response = await client.put(_url(item), headers=HEADERS, json={"rep_fields": {}})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Org spec" in detail["message"]
    assert [(e["path"], e["code"]) for e in detail["errors"]] == [
        ("/rep_fields/org/title_slug", "rep_fields_incomplete")
    ]
    assert "Org spec" in detail["errors"][0]["message"]
    [refusal] = detail["data"]["refusals"]
    assert refusal["rep_spec_id"] == str(spec.rep_spec_id)
    assert refusal["rep_spec_name"] == "Org spec"
    assert refusal["assignment_id"]
    assert refusal["code"] == "rep_fields_incomplete"
    assert refusal["errors"][0]["path"] == "/rep_fields/org/title_slug"


@pytest.mark.asyncio
async def test_put_names_every_broken_assignment(client, session):
    first = _spec("First", "org.title_slug")
    second = _spec(
        "Second",
        "info_item.name_slug",
        path_template="i/{info_item.name_slug}/{source_revision.id}",
    )
    item = await _assigned(
        session, {"org": {"title": "WA LCB"}, "info_item": {"name": "Notices"}}, first, second
    )

    response = await client.put(_url(item), headers=HEADERS, json={"rep_fields": {}})

    assert response.status_code == 422
    names = {r["rep_spec_name"] for r in response.json()["detail"]["data"]["refusals"]}
    assert names == {"First", "Second"}


@pytest.mark.asyncio
async def test_put_refuses_an_unrenderable_value(client, session):
    spec = _spec("Raw", "org.name", path_template="a/{org.name}/{source_revision.id}")
    item = await _assigned(session, {"org": {"name": "wa_lcb"}}, spec)

    response = await client.put(
        _url(item), headers=HEADERS, json={"rep_fields": {"org": {"name": "WA LCB"}}}
    )

    assert response.status_code == 422
    [error] = response.json()["detail"]["errors"]
    assert error["code"] == "rep_fields_unrenderable"
    assert error["path"] == "/rep_fields"
    assert "org.name" in error["message"]


@pytest.mark.asyncio
async def test_put_that_moves_a_destination_is_409_with_both_paths(client, session):
    spec = _spec("Org spec", "org.title_slug")
    item = await _assigned(session, {"org": {"title": "Old Name"}}, spec)

    response = await client.put(
        _url(item), headers=HEADERS, json={"rep_fields": {"org": {"title": "New Name"}}}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["kind"] == "conflict"
    assert [e["code"] for e in detail["errors"]] == ["rep_fields_moves_destination"]
    [move] = detail["data"]["moves"]
    assert move["rep_spec_name"] == "Org spec"
    assert move["before"].startswith("organizations/old_name/")
    assert move["after"].startswith("organizations/new_name/")
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "Old Name"}}


@pytest.mark.asyncio
async def test_put_moves_a_destination_when_allowed(client, session):
    item = await _assigned(session, {"org": {"title": "Old Name"}}, _spec("s", "org.title_slug"))

    response = await client.put(
        _url(item),
        headers=HEADERS,
        json={"rep_fields": {"org": {"title": "New Name"}}, "allow_destination_change": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["rep_fields"] == {"org": {"title": "New Name"}}


# ---------------------------------------------------------------------------
# POST /info-items shape-checks the bag even with no assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_refuses_a_bag_off_the_v1_shape_without_assignments(client):
    response = await client.post(
        "/api/v1/info-items", headers=HEADERS, json={"name": "Flat", "rep_fields": {"flat": "x"}}
    )

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("/rep_fields/flat", "rep_fields_invalid")]
