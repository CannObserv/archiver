"""The Notifications page, and the item and domain pages' views of it (archiver#363, D5).

A list grouped by scope, and create/edit/delete for everything but the Jinja
fields, which stay API-only until #367's preview - an edit carries them over.
The item page's "Notified by" row is ``subscriptions_for``'s answer; the domain
page lists its domain-scoped rows. Nothing here sends: there is no send or test
control, and no write leaves a ``changes_outbox`` row.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import (
    ChangesOutboxRow,
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    NotificationSubscription,
)

_HEADERS = {"X-ExeDev-UserID": "ext-notif", "X-ExeDev-Email": "notif@example.com"}
CHANNEL = "01M5APS9R7A0QEDB9522MRA4CT"
_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}]
_CONTENT_DEFAULTS = {"default__include_diff_snippet": "on", "default__diff_snippet_lines": "25"}


async def _domain(session, name: str) -> Domain:
    domain = Domain(name=name)
    session.add(domain)
    await session.flush()
    return domain


async def _item(session, host: str) -> InfoItem:
    item = InfoItem(name=f"item on {host}")
    source = InfoSource(url=f"https://{host}/{ULID()}", source_specs=_SPECS, domain_name=host)
    session.add_all([item, source])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()
    return item


async def _sub(session, title: str, scope: str = "global", **kw) -> NotificationSubscription:
    sub = NotificationSubscription(
        title=title,
        scope=scope,
        events=kw.pop("events", ["change_detected"]),
        remote_channel_id=CHANNEL,
        **kw,
    )
    session.add(sub)
    await session.flush()
    return sub


async def _outbox(session) -> int:
    return (await session.execute(select(func.count()).select_from(ChangesOutboxRow))).scalar_one()


def _form(**kw) -> dict:
    return {
        "title": "Ops",
        "scope": "global",
        "events": ["change_detected"],
        "remote_channel_id": CHANNEL,
        "is_active": "on",
        **_CONTENT_DEFAULTS,
    } | kw


# --- list -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_redirects(client):
    r = await client.get("/dashboard/notifications/", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_list_groups_by_scope_and_links_refs(client, session):
    domain = await _domain(session, "notif-list.example.com")
    item = await _item(session, "notif-list.example.com")
    await _sub(session, "Everyone hears")
    await _sub(session, "Host hears", "domain", domain_id=domain.id)
    await _sub(session, "Item hears", "item", info_item_id=item.info_item_id, is_active=False)

    r = await client.get("/dashboard/notifications/", headers=_HEADERS)

    assert r.status_code == 200
    text = r.text[r.text.index("<h1") :]
    assert text.index("Global") < text.index("Everyone hears") < text.index("Domain")
    assert text.index("Domain") < text.index("Host hears") < text.index("Item hears")
    assert 'href="/dashboard/domains/notif-list.example.com"' in text
    assert f'href="/dashboard/info-items/{item.info_item_id}"' in text
    assert "inactive" in text
    assert "/dashboard/notifications/new" in text


@pytest.mark.asyncio
async def test_the_sidebar_links_the_page(client):
    r = await client.get("/dashboard/notifications/", headers=_HEADERS)
    assert re.search(r'href="/dashboard/notifications/"[^>]*sidebar__link--active', r.text)


# --- create ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_form_prefills_from_the_query(client, session):
    await _domain(session, "prefill.example.com")
    r = await client.get(
        "/dashboard/notifications/new?scope=domain&domain=prefill.example.com", headers=_HEADERS
    )
    assert r.status_code == 200
    assert re.search(r'value="domain"[^>]*checked', r.text)
    assert re.search(r'value="prefill.example.com"[^>]*selected', r.text)
    # D5: the Jinja fields are not on the form until #367's preview.
    assert "title_template" not in r.text and "body_template" not in r.text


@pytest.mark.asyncio
async def test_create_global_redirects_and_publishes_nothing(client, session):
    before = await _outbox(session)

    r = await client.post(
        "/dashboard/notifications/new",
        headers=_HEADERS,
        data=_form(events=["watch_error", "change_detected"]),
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/notifications/"
    sub = (await session.execute(select(NotificationSubscription))).scalar_one()
    assert (sub.title, sub.scope, sub.is_active) == ("Ops", "global", True)
    assert sub.events == ["change_detected", "watch_error"]
    assert sub.content_config is None
    assert await _outbox(session) == before


@pytest.mark.asyncio
async def test_create_domain_and_item_scopes(client, session):
    domain = await _domain(session, "notif-new.example.com")
    item = await _item(session, "notif-new.example.com")

    for data in (
        _form(scope="domain", domain="notif-new.example.com", info_item_id=""),
        _form(scope="item", info_item_id=str(item.info_item_id), domain=""),
    ):
        r = await client.post(
            "/dashboard/notifications/new", headers=_HEADERS, data=data, follow_redirects=False
        )
        assert r.status_code == 303, r.text

    rows = {s.scope: s for s in (await session.execute(select(NotificationSubscription))).scalars()}
    assert rows["domain"].domain_id == domain.id
    assert rows["item"].info_item_id == item.info_item_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data, message",
    [
        (_form(events=[]), "at least one event"),
        (_form(remote_channel_id="dev-sink"), "not a Notifier channel id"),
        (_form(title=""), "Title"),
        (_form(scope="domain", domain="nowhere.example.com"), "no Domain row"),
        (_form(scope="item", info_item_id="not-a-ulid"), "InfoItem"),
        (_form(default__diff_snippet_lines="0"), "1-200"),
    ],
)
async def test_a_refused_create_re_renders_with_the_reason(client, session, data, message):
    r = await client.post("/dashboard/notifications/new", headers=_HEADERS, data=data)
    assert r.status_code == 422
    assert message in r.text
    assert (await session.execute(select(NotificationSubscription))).first() is None


# --- edit -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_form_fixes_the_scope_and_shows_the_options(client, session):
    domain = await _domain(session, "notif-edit.example.com")
    sub = await _sub(
        session,
        "Host",
        "domain",
        domain_id=domain.id,
        content_config={"overrides": {"watch_error": {"include_domain": True}}},
    )

    r = await client.get(f"/dashboard/notifications/{sub.id}/edit", headers=_HEADERS)

    assert r.status_code == 200
    assert 'name="scope"' not in r.text
    assert "notif-edit.example.com" in r.text
    assert re.search(r'name="override__watch_error"[^>]*checked', r.text)
    assert re.search(r'name="watch_error__include_domain"[^>]*checked', r.text)


@pytest.mark.asyncio
async def test_edit_saves_and_carries_the_api_set_templates_over(client, session):
    sub = await _sub(
        session,
        "Before",
        content_config={"default": {"title_template": "{{ item_name }}"}},
    )
    before = await _outbox(session)

    r = await client.post(
        f"/dashboard/notifications/{sub.id}/edit",
        headers=_HEADERS,
        data={
            "title": "After",
            "events": ["watch_recovered"],
            "remote_channel_id": CHANNEL,
            **_CONTENT_DEFAULTS,
            "default__include_domain": "on",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303, r.text
    await session.refresh(sub)
    assert (sub.title, sub.events, sub.is_active) == ("After", ["watch_recovered"], False)
    assert sub.content_config == {
        "default": {"include_domain": True, "title_template": "{{ item_name }}"}
    }
    assert sub.scope == "global"
    assert await _outbox(session) == before


@pytest.mark.asyncio
async def test_edit_refuses_to_drop_an_override_holding_a_template(client, session):
    stored = {"overrides": {"watch_error": {"body_template": "down"}}}
    sub = await _sub(session, "Kept", content_config=stored)

    r = await client.post(
        f"/dashboard/notifications/{sub.id}/edit",
        headers=_HEADERS,
        data=_form(title="Changed"),
    )

    assert r.status_code == 422
    assert "holds a Jinja template" in r.text
    await session.refresh(sub)
    assert (sub.title, sub.content_config) == ("Kept", stored)


@pytest.mark.asyncio
async def test_a_missing_subscription_is_a_404(client):
    r = await client.get(f"/dashboard/notifications/{ULID()}/edit", headers=_HEADERS)
    assert r.status_code == 404
    r = await client.get("/dashboard/notifications/not-a-ulid/edit", headers=_HEADERS)
    assert r.status_code == 404


# --- delete ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_redirects_and_removes_the_row(client, session):
    sub = await _sub(session, "Doomed")

    r = await client.post(
        f"/dashboard/notifications/{sub.id}/delete", headers=_HEADERS, follow_redirects=False
    )

    assert r.status_code == 303
    assert await session.get(NotificationSubscription, sub.id) is None


@pytest.mark.asyncio
async def test_no_page_offers_a_send_or_test_control(client, session):
    sub = await _sub(session, "Quiet")
    for url in (
        "/dashboard/notifications/",
        "/dashboard/notifications/new",
        f"/dashboard/notifications/{sub.id}/edit",
    ):
        text = (await client.get(url, headers=_HEADERS)).text
        actions = re.findall(r'action="([^"]+)"', text)
        assert not [a for a in actions if "send" in a or "test" in a], url


# --- the item and domain pages --------------------------------------------


@pytest.mark.asyncio
async def test_item_page_notified_by_lists_global_domain_and_item_rows(client, session):
    domain = await _domain(session, "notified.example.com")
    item = await _item(session, "notified.example.com")
    await _sub(session, "Global row", events=["change_detected", "watch_error"])
    await _sub(session, "Domain row", "domain", domain_id=domain.id, events=["watch_error"])
    await _sub(session, "Item row", "item", info_item_id=item.info_item_id)
    await _sub(session, "Paused row", is_active=False)

    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)

    assert r.status_code == 200
    row = r.text[r.text.index('id="ii-notified-by"') :]
    row = row[: row.index("</section>")]
    for title in ("Global row", "Domain row", "Item row"):
        assert title in row
    assert "Paused row" not in row
    assert row.count('href="/dashboard/notifications/') == 3
    assert "Change, Error" in row


@pytest.mark.asyncio
async def test_item_page_with_no_subscriptions_offers_to_add_one(client, session):
    item = await _item(session, "lonely.example.com")
    r = await client.get(f"/dashboard/info-items/{item.info_item_id}", headers=_HEADERS)
    assert "Notified by" in r.text
    assert f"/dashboard/notifications/new?scope=item&amp;info_item_id={item.info_item_id}" in r.text


@pytest.mark.asyncio
async def test_domain_page_lists_its_domain_scoped_subscriptions(client, session):
    domain = await _domain(session, "domain-subs.example.com")
    other = await _domain(session, "other-subs.example.com")
    mine = await _sub(session, "Mine", "domain", domain_id=domain.id, is_active=False)
    await _sub(session, "Theirs", "domain", domain_id=other.id)
    await _sub(session, "Everyone")

    r = await client.get("/dashboard/domains/domain-subs.example.com", headers=_HEADERS)

    assert r.status_code == 200
    assert "Notification subscriptions (1)" in r.text
    assert f'href="/dashboard/notifications/{mine.id}/edit"' in r.text
    assert "Theirs" not in r.text and "Everyone" not in r.text
    assert "/dashboard/notifications/new?scope=domain&amp;domain=domain-subs.example.com" in r.text
