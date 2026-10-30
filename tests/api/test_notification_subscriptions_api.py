"""Notification subscriptions over the API (archiver#363, D3/D4).

``GET``/``POST /notification-subscriptions``, ``GET``/``PATCH``/``DELETE
/notification-subscriptions/{id}``. The scope and its ref are fixed at create
(re-scope = delete + create); ``PATCH`` replaces ``content_config`` whole.
Validation is at write time and stricter than Watcher's. Nothing here sends or
publishes: no write leaves a ``changes_outbox`` row.
"""

import pytest
from sqlalchemy import func, select

from src.core.models import ChangesOutboxRow

HEADERS = {"X-API-Key": "test-secret-key"}
URL = "/api/v1/notification-subscriptions"
CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"
OTHER_CHANNEL = "01M5APS9R7A0QEDB9522MRA4CV"
MISSING = "01JZZZZZZZZZZZZZZZZZZZZZZZ"
_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "body"},
    "fingerprint": {},
}


def _body(**kw) -> dict:
    return {
        "title": "Ops",
        "scope": "global",
        "events": ["change_detected"],
        "remote_channel_id": CHANNEL,
    } | kw


async def _item(client, host: str = "subs-api.example.com") -> str:
    resp = await client.post(
        "/api/v1/info-items",
        headers=HEADERS,
        json={
            "name": "Watched",
            "initial_url": f"https://{host}/a",
            "initial_source_specs": [_SPEC],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["info_item_id"]


async def _domain(client, name: str = "subs-api.example.com") -> str:
    resp = await client.patch(f"/api/v1/domains/{name}", headers=HEADERS, json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create(client, **kw) -> dict:
    resp = await client.post(URL, headers=HEADERS, json=_body(**kw))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _outbox_count(session) -> int:
    return (await session.execute(select(func.count()).select_from(ChangesOutboxRow))).scalar_one()


def _paths(resp) -> list[str]:
    return [e["path"] for e in resp.json()["detail"]["errors"]]


# --- create ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_global_returns_the_row_and_publishes_nothing(client, session):
    before = await _outbox_count(session)

    body = await _create(client)

    assert body["title"] == "Ops"
    assert body["scope"] == "global"
    assert body["domain_id"] is None and body["domain"] is None
    assert body["info_item_id"] is None
    assert body["events"] == ["change_detected"]
    assert body["remote_channel_id"] == CHANNEL
    assert body["is_active"] is True
    assert body["content_config"] is None
    assert body["imported_watcher_id"] is None
    assert body["id"] and body["created_at"] and body["updated_at"]
    assert await _outbox_count(session) == before


@pytest.mark.asyncio
async def test_create_domain_scope_names_the_domain_by_hostname(client):
    domain_id = await _domain(client)

    body = await _create(client, scope="domain", domain="subs-api.example.com")

    assert body["domain_id"] == domain_id
    assert body["domain"] == "subs-api.example.com"


@pytest.mark.asyncio
async def test_create_item_scope(client):
    item_id = await _item(client)

    body = await _create(client, scope="item", info_item_id=item_id)

    assert body["info_item_id"] == item_id
    assert body["domain"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra, path",
    [
        ({"scope": "global", "domain": "x.example.com"}, "/domain"),
        ({"scope": "global", "info_item_id": MISSING}, "/info_item_id"),
        ({"scope": "domain"}, "/domain"),
        ({"scope": "item"}, "/info_item_id"),
        ({"scope": "domain", "domain": "x.example.com", "info_item_id": MISSING}, "/info_item_id"),
    ],
)
async def test_the_ref_must_match_the_scope_exactly(client, extra, path):
    resp = await client.post(URL, headers=HEADERS, json=_body(**extra))
    assert resp.status_code == 422, resp.text
    assert path in _paths(resp)


@pytest.mark.asyncio
async def test_a_domain_with_no_row_is_a_422_on_the_field(client):
    resp = await client.post(URL, headers=HEADERS, json=_body(scope="domain", domain="no-row.test"))
    assert resp.status_code == 422
    assert _paths(resp) == ["/domain"]


@pytest.mark.asyncio
async def test_a_missing_item_is_a_422_on_the_field(client):
    resp = await client.post(URL, headers=HEADERS, json=_body(scope="item", info_item_id=MISSING))
    assert resp.status_code == 422
    assert _paths(resp) == ["/info_item_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events", [[], ["digest"], ["change_detected", "created"], "change_detected"]
)
async def test_events_must_be_a_non_empty_list_of_known_events(client, events):
    resp = await client.post(URL, headers=HEADERS, json=_body(events=events))
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_events_are_stored_deduplicated_in_declaration_order(client):
    body = await _create(
        client, events=["watch_recovered", "change_detected", "watch_recovered", "watch_error"]
    )
    assert body["events"] == ["change_detected", "watch_error", "watch_recovered"]


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["dev-sink", "01M5APS9R7A0QEDB9522MRA4C", "", None])
async def test_the_channel_must_be_ulid_shaped(client, channel):
    resp = await client.post(URL, headers=HEADERS, json=_body(remote_channel_id=channel))
    assert resp.status_code == 422
    assert "/remote_channel_id" in _paths(resp)


@pytest.mark.asyncio
async def test_a_lowercase_channel_is_normalized(client):
    body = await _create(client, remote_channel_id=CHANNEL.lower())
    assert body["remote_channel_id"] == CHANNEL


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["", "   ", "x" * 101])
async def test_title_is_1_to_100_characters(client, title):
    resp = await client.post(URL, headers=HEADERS, json=_body(title=title))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_body_keys_are_refused(client):
    resp = await client.post(URL, headers=HEADERS, json=_body(channel_hint="#ops"))
    assert resp.status_code == 422
    assert "/channel_hint" in _paths(resp)


@pytest.mark.asyncio
async def test_content_config_is_stored_as_sent(client):
    config = {"default": {"include_domain": True}, "overrides": {"watch_error": {}}}
    body = await _create(client, content_config=config)
    assert body["content_config"] == config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config, path",
    [
        (
            {"default": {"include_significance": True}},
            "/content_config/default/include_significance",
        ),
        ({"overrides": {"digest": {}}}, "/content_config/overrides/digest/[key]"),
        ({"default": {"diff_snippet_lines": 0}}, "/content_config/default/diff_snippet_lines"),
        (
            {"overrides": {"watch_error": {"body_template": "{% if %}"}}},
            "/content_config/overrides/watch_error/body_template",
        ),
    ],
)
async def test_content_config_is_validated_at_write_time(client, config, path):
    resp = await client.post(URL, headers=HEADERS, json=_body(content_config=config))
    assert resp.status_code == 422, resp.text
    assert path in _paths(resp)


@pytest.mark.asyncio
async def test_a_jinja_error_names_the_problem(client):
    resp = await client.post(
        URL,
        headers=HEADERS,
        json=_body(content_config={"default": {"title_template": "{{ unclosed"}}),
    )
    assert resp.status_code == 422
    assert "Jinja" in resp.json()["detail"]["errors"][0]["message"]


@pytest.mark.asyncio
async def test_imported_watcher_id_is_set_on_create_and_unique(client):
    watcher_id = "01KQN12MHJJHFETN2XMDF98GHA"
    body = await _create(client, imported_watcher_id=watcher_id)
    assert body["imported_watcher_id"] == watcher_id

    again = await client.post(URL, headers=HEADERS, json=_body(imported_watcher_id=watcher_id))
    assert again.status_code == 409
    assert again.json()["detail"]["kind"] == "conflict"


# --- read / list ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_id_and_404(client):
    created = await _create(client)
    resp = await client.get(f"{URL}/{created['id']}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == created

    assert (await client.get(f"{URL}/{MISSING}", headers=HEADERS)).status_code == 404
    assert (await client.get(f"{URL}/not-a-ulid", headers=HEADERS)).status_code == 422


@pytest.mark.asyncio
async def test_list_filters_and_page_shape(client):
    await _domain(client, "list-a.example.com")
    await _domain(client, "list-b.example.com")
    item_id = await _item(client, "list-item.example.com")
    g = await _create(client)
    off = await _create(client, is_active=False)
    a = await _create(client, scope="domain", domain="list-a.example.com")
    b = await _create(client, scope="domain", domain="list-b.example.com")
    i = await _create(client, scope="item", info_item_id=item_id)

    async def ids(**params) -> list[str]:
        resp = await client.get(URL, headers=HEADERS, params=params)
        assert resp.status_code == 200, resp.text
        return [row["id"] for row in resp.json()["items"]]

    everything = await ids()
    assert [g["id"], off["id"], a["id"], b["id"], i["id"]] == [
        x for x in everything if x in {g["id"], off["id"], a["id"], b["id"], i["id"]}
    ]
    assert await ids(scope="domain") == [a["id"], b["id"]]
    assert await ids(domain="list-a.example.com") == [a["id"]]
    assert await ids(domain="no-such.example.com") == []
    assert await ids(info_item_id=item_id) == [i["id"]]
    assert off["id"] in await ids(is_active="false")
    assert off["id"] not in await ids(is_active="true")

    page = (await client.get(URL, headers=HEADERS, params={"limit": 1})).json()
    assert set(page) == {"items", "has_more", "limit", "offset"}
    assert page["limit"] == 1 and page["offset"] == 0 and page["has_more"] is True


@pytest.mark.asyncio
async def test_list_limit_over_500_is_a_422(client):
    assert (await client.get(URL, headers=HEADERS, params={"limit": 501})).status_code == 422


@pytest.mark.asyncio
async def test_list_rejects_an_unknown_scope(client):
    assert (await client.get(URL, headers=HEADERS, params={"scope": "everyone"})).status_code == 422


# --- patch ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_updates_only_the_fields_sent(client, session):
    created = await _create(client, content_config={"default": {"include_tags": True}})
    before = await _outbox_count(session)

    resp = await client.patch(
        f"{URL}/{created['id']}",
        headers=HEADERS,
        json={"title": "Renamed", "events": ["watch_error"], "is_active": False},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["events"] == ["watch_error"]
    assert body["is_active"] is False
    assert body["remote_channel_id"] == CHANNEL
    assert body["content_config"] == {"default": {"include_tags": True}}
    assert body["updated_at"] >= created["updated_at"]
    assert await _outbox_count(session) == before


@pytest.mark.asyncio
async def test_patch_replaces_content_config_whole_and_null_is_defaults(client):
    created = await _create(
        client, content_config={"default": {"include_tags": True}, "overrides": {"watch_error": {}}}
    )
    url = f"{URL}/{created['id']}"

    replaced = await client.patch(
        url, headers=HEADERS, json={"content_config": {"default": {"include_domain": True}}}
    )
    assert replaced.json()["content_config"] == {"default": {"include_domain": True}}

    cleared = await client.patch(url, headers=HEADERS, json={"content_config": None})
    assert cleared.status_code == 200
    assert cleared.json()["content_config"] is None


@pytest.mark.asyncio
async def test_patch_changes_the_channel(client):
    created = await _create(client)
    resp = await client.patch(
        f"{URL}/{created['id']}", headers=HEADERS, json={"remote_channel_id": OTHER_CHANNEL}
    )
    assert resp.json()["remote_channel_id"] == OTHER_CHANNEL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [
        ("scope", "item"),
        ("domain", "x.example.com"),
        ("info_item_id", MISSING),
        ("imported_watcher_id", MISSING),
        ("id", MISSING),
    ],
)
async def test_patch_refuses_the_scope_its_ref_and_the_import_key(client, field, value):
    created = await _create(client)
    resp = await client.patch(f"{URL}/{created['id']}", headers=HEADERS, json={field: value})
    assert resp.status_code == 422
    assert f"/{field}" in _paths(resp)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["title", "events", "remote_channel_id", "is_active"])
async def test_patch_refuses_null_on_a_required_field(client, field):
    created = await _create(client)
    resp = await client.patch(f"{URL}/{created['id']}", headers=HEADERS, json={field: None})
    assert resp.status_code == 422
    assert f"/{field}" in _paths(resp)


@pytest.mark.asyncio
async def test_patch_validates_like_create(client):
    created = await _create(client)
    resp = await client.patch(
        f"{URL}/{created['id']}",
        headers=HEADERS,
        json={"content_config": {"default": {"body_template": "{% for %}"}}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_a_missing_subscription_is_a_404(client):
    resp = await client.patch(f"{URL}/{MISSING}", headers=HEADERS, json={"title": "x"})
    assert resp.status_code == 404


# --- delete ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_then_404(client, session):
    created = await _create(client)
    before = await _outbox_count(session)

    resp = await client.delete(f"{URL}/{created['id']}", headers=HEADERS)

    assert resp.status_code == 204
    assert (await client.get(f"{URL}/{created['id']}", headers=HEADERS)).status_code == 404
    assert (await client.delete(f"{URL}/{created['id']}", headers=HEADERS)).status_code == 404
    assert await _outbox_count(session) == before


@pytest.mark.asyncio
async def test_item_delete_cascades_its_subscriptions_and_still_tombstones(client, session):
    item_id = await _item(client, "cascade.example.com")
    sub = await _create(client, scope="item", info_item_id=item_id)
    glob = await _create(client)

    resp = await client.delete(f"/api/v1/info-items/{item_id}", headers=HEADERS)

    assert resp.status_code == 204, resp.text
    assert (await client.get(f"{URL}/{sub['id']}", headers=HEADERS)).status_code == 404
    assert (await client.get(f"{URL}/{glob['id']}", headers=HEADERS)).status_code == 200
    payloads = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.registry")
        )
    ).scalars()
    mine = [p for p in payloads if p["info_item_id"] == item_id]
    # The SELECT has no ORDER BY, so the newest announcement is the highest
    # generation, not the last row: CI returned generation 2 before 1 (#368 deploy).
    assert mine and max(mine, key=lambda p: p["generation"])["revoked"] is True


@pytest.mark.asyncio
async def test_routes_need_an_api_key(client):
    assert (await client.get(URL)).status_code == 403
    assert (await client.post(URL, json=_body())).status_code == 403
