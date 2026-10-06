"""PUT /info-items/{id}/org and InfoItemOut.org — the Power Map org link (archiver#304)."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.api.deps import get_power_map
from src.api.main import app
from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.power_map import PowerMapUnavailableError
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, FakePowerMap, org

HEADERS = {"X-API-Key": "test-secret-key"}
_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"


@pytest.fixture
def power_map():
    pm = FakePowerMap(org())
    app.dependency_overrides[get_power_map] = lambda: pm
    yield pm
    app.dependency_overrides.pop(get_power_map, None)


@pytest.fixture
def no_power_map():
    app.dependency_overrides[get_power_map] = lambda: None
    yield
    app.dependency_overrides.pop(get_power_map, None)


async def _item(session, bag: dict | None = None, *, spec: RepSpec | None = None) -> InfoItem:
    item = InfoItem(name="org item", rep_fields=bag or {})
    session.add(item)
    if spec is not None:
        session.add(spec)
    await session.flush()
    if spec is not None:
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
        await session.flush()
    return item


def _spec() -> RepSpec:
    return RepSpec(
        provider="gcs",
        name="org spec",
        schema_version=1,
        document={"required_fields": ["org.title_slug"], "path_template": _ORG_PATH},
    )


def _url(item: InfoItem | str) -> str:
    item_id = item if isinstance(item, str) else item.info_item_id
    return f"/api/v1/info-items/{item_id}/org"


# ---------------------------------------------------------------------------
# Link / unlink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_returns_the_item_with_its_org(client, session, power_map):
    item = await _item(session)

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pm_org_id"] == WSLCB_ID
    assert body["org"]["pm_org_id"] == WSLCB_ID
    assert body["org"]["name"] == WSLCB_NAME
    assert body["org"]["acronym"] == "WSLCB"
    assert body["org"]["active"] is True
    for notice in ("archived_at", "succeeded_by", "merged_into", "renamed_from", "missing_since"):
        assert body["org"][notice] is None, notice


@pytest.mark.asyncio
async def test_get_shows_the_linked_org_and_unlinked_items_show_null(client, session, power_map):
    linked = await _item(session)
    unlinked = await _item(session)
    await client.put(_url(linked), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    got = (await client.get(f"/api/v1/info-items/{linked.info_item_id}", headers=HEADERS)).json()
    bare = (await client.get(f"/api/v1/info-items/{unlinked.info_item_id}", headers=HEADERS)).json()

    assert got["org"]["name"] == WSLCB_NAME
    assert bare["pm_org_id"] is None
    assert bare["org"] is None


@pytest.mark.asyncio
async def test_list_carries_each_items_org(client, session, power_map):
    linked = await _item(session)
    await client.put(_url(linked), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    items = (await client.get("/api/v1/info-items?limit=500", headers=HEADERS)).json()["items"]

    (row,) = [i for i in items if i["info_item_id"] == str(linked.info_item_id)]
    assert row["org"]["name"] == WSLCB_NAME


@pytest.mark.asyncio
async def test_unlink_with_null(client, session, power_map):
    item = await _item(session)
    await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": None})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pm_org_id"] is None
    assert body["org"] is None
    assert body["rep_fields"] == {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}}


@pytest.mark.asyncio
async def test_unlink_needs_no_power_map(client, session, no_power_map):
    item = await _item(session, {"org": {"title": "WA LCB"}})
    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": None})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_pm_org_id_is_required_explicitly(client, session, power_map):
    item = await _item(session)
    response = await client.put(_url(item), headers=HEADERS, json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pm_org_id_must_be_a_ulid(client, session, power_map):
    item = await _item(session)
    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": "not-a-ulid"})
    assert response.status_code == 422
    assert power_map.calls == []


@pytest.mark.asyncio
async def test_requires_an_api_key(client, session, power_map):
    item = await _item(session)
    response = await client.put(_url(item), json={"pm_org_id": WSLCB_ID})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_item_is_404(client, power_map):
    response = await client.put(_url(str(ULID())), headers=HEADERS, json={"pm_org_id": WSLCB_ID})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Power Map's answers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_power_map_unavailable_is_503_and_links_nothing(client, session, power_map):
    item = await _item(session)
    power_map.unavailable = PowerMapUnavailableError("rate limited (HTTP 429)", retry_after=7.0)

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    assert response.status_code == 503, response.text
    body = response.json()["detail"]
    assert body["kind"] == "server"
    assert body["data"] == {"reason": "rate limited (HTTP 429)", "retry_after": 7.0}
    assert response.headers.get("retry-after") == "7"
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_power_map_not_configured_is_503(client, session, no_power_map):
    item = await _item(session)
    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_an_org_power_map_does_not_have_is_422(client, session, power_map):
    item = await _item(session)
    missing = str(ULID())
    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": missing})
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["errors"][0]["path"] == "/pm_org_id"
    assert body["errors"][0]["code"] == "pm_org_not_found"


@pytest.mark.asyncio
async def test_an_org_with_no_name_is_422(client, session, power_map):
    power_map.plant(org(name=None))
    item = await _item(session)
    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["code"] == "pm_org_unnamed"


# ---------------------------------------------------------------------------
# Hand-typed keys and the move contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_drops_hand_typed_keys_equal_to_power_maps(client, session, power_map):
    item = await _item(session, {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}}, spec=_spec())

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    assert response.status_code == 200, response.text
    assert response.json()["rep_fields"] == {}


@pytest.mark.asyncio
async def test_a_link_that_moves_a_path_is_409_with_both_paths(client, session, power_map):
    item = await _item(session, {"org": {"title": "WA LCB"}}, spec=_spec())

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    assert response.status_code == 409, response.text
    body = response.json()["detail"]
    assert body["errors"][0]["code"] == "rep_fields_moves_destination"
    (move,) = body["data"]["moves"]
    assert move["rep_spec_name"] == "org spec"
    assert move["before"].startswith("organizations/wa_lcb/")
    assert move["after"].startswith("organizations/washington_state_liquor_and_cannabis_board/")
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_a_moving_link_is_stored_when_allowed(client, session, power_map):
    item = await _item(session, {"org": {"title": "WA LCB"}}, spec=_spec())

    response = await client.put(
        _url(item),
        headers=HEADERS,
        json={"pm_org_id": WSLCB_ID, "allow_destination_change": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["pm_org_id"] == WSLCB_ID


@pytest.mark.asyncio
async def test_a_link_that_breaks_an_assignment_is_422_naming_it(client, session, power_map):
    power_map.plant(org(acronym=None))
    spec = RepSpec(
        provider="gcs",
        name="acronym spec",
        schema_version=1,
        document={"required_fields": ["org.acronym"], "path_template": "{org.acronym}/x"},
    )
    item = await _item(session, {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}}, spec=spec)

    response = await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    assert response.status_code == 422, response.text
    body = response.json()["detail"]
    assert body["data"]["refusals"][0]["rep_spec_name"] == "acronym spec"
    assert body["errors"][0]["code"] == "rep_fields_incomplete"


# ---------------------------------------------------------------------------
# While linked: PUT /rep-fields refuses the org's keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_rep_fields_refuses_org_title_while_linked(client, session, power_map):
    item = await _item(session)
    await client.put(_url(item), headers=HEADERS, json={"pm_org_id": WSLCB_ID})

    response = await client.put(
        f"/api/v1/info-items/{item.info_item_id}/rep-fields",
        headers=HEADERS,
        json={"rep_fields": {"org": {"title": "Hand Typed", "title_slug": "ok"}}},
    )

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [
        ("/rep_fields/org/title", "rep_fields_invalid")
    ]


# ---------------------------------------------------------------------------
# POST /info-items with pm_org_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_can_link_an_org(client, session, power_map):
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "born linked", "pm_org_id": WSLCB_ID},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pm_org_id"] == WSLCB_ID
    assert body["org"]["name"] == WSLCB_NAME


@pytest.mark.asyncio
async def test_create_with_an_org_satisfies_an_assignment_through_it(client, session, power_map):
    spec = _spec()
    session.add(spec)
    await session.flush()

    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "born linked and assigned",
            "pm_org_id": WSLCB_ID,
            "initial_rep_spec_assignments": [{"rep_spec_id": str(spec.rep_spec_id)}],
        },
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["title", "acronym"])
async def test_create_refuses_an_org_owned_key_alongside_an_org(client, power_map, key):
    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "conflicted", "pm_org_id": WSLCB_ID, "rep_fields": {"org": {key: "X"}}},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["errors"][0]["path"] == f"/rep_fields/org/{key}"


@pytest.mark.asyncio
async def test_create_with_power_map_down_is_503_and_creates_nothing(client, session, power_map):
    power_map.unavailable = PowerMapUnavailableError("request timed out")

    response = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={"name": "never born", "pm_org_id": WSLCB_ID},
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_create_without_an_org_never_asks_power_map(client, power_map):
    response = await client.post("/api/v1/info-items", headers=HEADERS, json={"name": "plain"})
    assert response.status_code == 201
    assert response.json()["org"] is None
    assert power_map.calls == []
