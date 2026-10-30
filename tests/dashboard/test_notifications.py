"""The Notifications page, and the item and domain pages' views of it (archiver#363, #367).

A list grouped by scope, and create/edit/delete, the Jinja fields included since
#367 put a live preview beside them (D5). The item page's "Notified by" row is
``subscriptions_for``'s answer; the domain page lists its domain-scoped rows.
The one send is the edit page's test-send (D6), an operator action through the
adapter's one dispatch. No write leaves a ``changes_outbox`` row.
"""

from __future__ import annotations

import json
import logging
import re
import threading

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.api.deps import get_notifier
from src.api.main import app
from src.core.models import (
    ChangesOutboxRow,
    Domain,
    InfoItem,
    InfoItemSource,
    InfoSource,
    NotificationSubscription,
)
from src.core.notifier.client import Dispatched, NotifierUnavailable
from src.dashboard.routes import notifications as routes
from tests.core.notifier.fake import DEV_SINK, FakeNotifier

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
    # #367 D5: the Jinja fields are on the form, with the live preview beside them.
    assert 'name="default__title_template"' in r.text
    assert 'name="watch_error__body_template"' in r.text
    assert 'hx-post="/dashboard/notifications/preview"' in r.text


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
async def test_edit_saves_the_templates_on_the_form(client, session):
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
            "default__body_template": "up: {{ item_name }}",
        },
        follow_redirects=False,
    )

    assert r.status_code == 303, r.text
    await session.refresh(sub)
    assert (sub.title, sub.events, sub.is_active) == ("After", ["watch_recovered"], False)
    # No carry-over: the cleared title field cleared the stored title template.
    assert sub.content_config == {
        "default": {"include_domain": True, "body_template": "up: {{ item_name }}"}
    }
    assert sub.scope == "global"
    assert await _outbox(session) == before


@pytest.mark.asyncio
async def test_the_edit_form_shows_the_stored_templates(client, session):
    sub = await _sub(
        session, "Shown", content_config={"overrides": {"watch_error": {"body_template": "x<y"}}}
    )
    r = await client.get(f"/dashboard/notifications/{sub.id}/edit", headers=_HEADERS)
    assert re.search(r'name="watch_error__body_template"[^>]*>x&lt;y</textarea>', r.text)


@pytest.mark.asyncio
async def test_an_override_holding_a_template_can_be_turned_off(client, session):
    sub = await _sub(
        session, "Kept", content_config={"overrides": {"watch_error": {"body_template": "down"}}}
    )
    r = await client.post(
        f"/dashboard/notifications/{sub.id}/edit",
        headers=_HEADERS,
        data=_form(title="Changed"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    await session.refresh(sub)
    assert (sub.title, sub.content_config) == ("Changed", None)


@pytest.mark.asyncio
async def test_a_template_that_does_not_parse_is_refused_on_save(client, session):
    sub = await _sub(session, "Kept")
    r = await client.post(
        f"/dashboard/notifications/{sub.id}/edit",
        headers=_HEADERS,
        data=_form(default__body_template="{% if %}"),
    )
    assert r.status_code == 422
    assert "Default: body template: not a valid Jinja template" in r.text
    # What was typed stays in the field.
    assert "{% if %}</textarea>" in r.text
    await session.refresh(sub)
    assert sub.content_config is None


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
async def test_only_the_edit_page_offers_a_test_send(client, session):
    """D6: the edit page's one button; the list and the create form have none."""
    sub = await _sub(session, "Quiet")
    for url in ("/dashboard/notifications/", "/dashboard/notifications/new"):
        text = (await client.get(url, headers=_HEADERS)).text
        assert "test-send" not in text, url
    text = (await client.get(f"/dashboard/notifications/{sub.id}/edit", headers=_HEADERS)).text
    assert text.count("test-send") >= 1
    assert re.findall(r'hx-post="([^"]*test-send)"', text) == [
        f"/dashboard/notifications/{sub.id}/test-send"
    ]
    # A static confirm that names the channel.
    assert re.search(rf'hx-confirm="[^"]*{CHANNEL}[^"]*"', text)


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


@pytest.mark.asyncio
async def test_a_refused_form_keeps_the_content_options_posted(client, session):
    """CR 2: a refusal elsewhere on the form must not reset the content options."""
    sub = await _sub(session, "Kept")
    posted = _form(
        title="",
        default__include_domain="on",
        override__watch_error="on",
        watch_error__diff_snippet_lines="7",
    )
    for url in ("/dashboard/notifications/new", f"/dashboard/notifications/{sub.id}/edit"):
        r = await client.post(url, headers=_HEADERS, data=posted)
        assert r.status_code == 422, url
        assert re.search(r'name="default__include_domain"[^>]*checked', r.text), url
        assert re.search(r'name="override__watch_error"[^>]*checked', r.text), url
        assert re.search(r'name="watch_error__diff_snippet_lines"[^>]*value="7"', r.text), url


@pytest.mark.asyncio
async def test_group_headings_count_every_row_not_the_page(client, session):
    """CR 4: SCREENS.md (#82) - a heading counts from a route COUNT, never |length."""
    for n in range(3):
        await _sub(session, f"Paged {n}")

    r = await client.get("/dashboard/notifications/?limit=1", headers=_HEADERS)

    assert "Global (3)" in r.text
    assert "Domain (0)" in r.text


# --- the preview (archiver#367, D5) ---------------------------------------


@pytest.mark.asyncio
async def test_the_preview_renders_the_posted_form_without_notifier(client, session):
    notifier = FakeNotifier(DEV_SINK)
    app.dependency_overrides[get_notifier] = lambda: notifier
    r = await client.post(
        "/dashboard/notifications/preview",
        headers=_HEADERS,
        data=_form(
            preview_event="watch_error",
            default__title_template="down: {{ item_name }} <b>",
        ),
    )
    assert r.status_code == 200
    assert 'id="notif-preview"' in r.text
    assert "down: Example item &lt;b&gt;" in r.text
    assert "returned HTTP 503" in r.text
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_the_preview_shows_the_error(client, session):
    r = await client.post(
        "/dashboard/notifications/preview",
        headers=_HEADERS,
        data=_form(preview_event="change_detected", default__body_template="{{ status_code }}"),
    )
    assert r.status_code == 200
    assert "UndefinedError" in r.text
    assert "status_code" in r.text


@pytest.mark.asyncio
async def test_the_preview_needs_a_login(client):
    r = await client.post("/dashboard/notifications/preview", data=_form(), follow_redirects=False)
    assert r.status_code in (303, 307)


# --- the test-send (archiver#367, D6) -------------------------------------


def _flash(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])["showFlash"]


@pytest.mark.asyncio
async def test_a_test_send_dispatches_the_rows_options_once(client, session, caplog):
    notifier = FakeNotifier(DEV_SINK)
    app.dependency_overrides[get_notifier] = lambda: notifier
    sub = await _sub(
        session,
        "Ops",
        content_config={"default": {"title_template": "{{ event_label }} on {{ item_name }}"}},
    )
    before = await _outbox(session)

    with caplog.at_level(logging.INFO, logger="src.dashboard.routes.notifications"):
        r = await client.post(
            f"/dashboard/notifications/{sub.id}/test-send",
            headers=_HEADERS | {"HX-Request": "true"},
        )

    assert r.status_code == 200
    assert notifier.calls == ["dispatch_composed"]
    (sent,) = notifier.dispatches
    assert sent["channel_id"] == CHANNEL
    assert sent["title"] == "[Test] Change on Example item"
    assert sent["body"].startswith("- Example item\n")
    assert re.fullmatch(
        rf"archiver:test:{sub.id}:[0-9A-HJKMNP-TV-Z]{{26}}", sent["idempotency_key"]
    )
    assert sent["metadata"] == {"test": True, "subscription_id": str(sub.id)}
    flash = _flash(r)
    assert flash["level"] == "success"
    assert "01M5DISPATCH0000000000000A" in flash["body"]
    assert "01M5DISPATCH0000000000000A" in r.text
    (line,) = [
        rec
        for rec in caplog.records
        if rec.name == "src.dashboard.routes.notifications" and "test-send" in rec.getMessage()
    ]
    assert (line.subscription_id, line.channel_id, line.dispatch_id) == (
        str(sub.id),
        CHANNEL,
        "01M5DISPATCH0000000000000A",
    )
    assert "Example item" not in str(line.__dict__)
    assert sent["idempotency_key"] not in str(line.__dict__)
    assert await _outbox(session) == before


@pytest.mark.asyncio
async def test_each_test_send_has_its_own_key(client, session):
    notifier = FakeNotifier(DEV_SINK)
    app.dependency_overrides[get_notifier] = lambda: notifier
    sub = await _sub(session, "Twice")
    for _ in range(2):
        await client.post(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    keys = {d["idempotency_key"] for d in notifier.dispatches}
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_a_failed_dispatch_status_is_a_warning(client, session):
    notifier = FakeNotifier(DEV_SINK)
    notifier.dispatched = Dispatched(id="01M5DISPATCH0000000000000B", status="failed")
    app.dependency_overrides[get_notifier] = lambda: notifier
    sub = await _sub(session, "Failing")
    r = await client.post(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    flash = _flash(r)
    assert flash["level"] == "warning"
    assert "failed" in flash["body"] and "01M5DISPATCH0000000000000B" in flash["body"]


@pytest.mark.asyncio
async def test_a_refused_test_send_shows_the_reason(client, session):
    notifier = FakeNotifier(
        unavailable=NotifierUnavailable("Notifier has no such channel in this tenant (HTTP 404)")
    )
    app.dependency_overrides[get_notifier] = lambda: notifier
    sub = await _sub(session, "Nowhere")
    r = await client.post(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    assert r.status_code == 200
    flash = _flash(r)
    assert flash["level"] == "error"
    assert "no such channel" in flash["body"]


@pytest.mark.asyncio
async def test_a_dormant_notifier_sends_nothing(client, session):
    app.dependency_overrides[get_notifier] = lambda: None
    sub = await _sub(session, "Dormant")
    r = await client.post(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    assert r.status_code == 200
    flash = _flash(r)
    assert flash["level"] == "error"
    assert "not configured" in flash["body"]


@pytest.mark.asyncio
async def test_a_test_send_needs_a_login_and_a_row(client, session):
    notifier = FakeNotifier(DEV_SINK)
    app.dependency_overrides[get_notifier] = lambda: notifier
    sub = await _sub(session, "Guarded")
    r = await client.post(f"/dashboard/notifications/{sub.id}/test-send", follow_redirects=False)
    assert r.status_code in (303, 307)
    r = await client.post(f"/dashboard/notifications/{ULID()}/test-send", headers=_HEADERS)
    assert r.status_code == 404
    r = await client.get(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    assert r.status_code in (404, 405)
    assert notifier.dispatches == []


@pytest.mark.asyncio
async def test_preview_and_test_send_render_off_the_event_loop(client, session, monkeypatch):
    """CR 1: an operator's template renders in a worker thread, so a slow one
    can't block the loop that serves the API and the consumers."""
    threads = []
    real_preview, real_compose = routes.render_preview, routes.compose

    def spy_preview(*a, **k):
        threads.append(threading.current_thread())
        return real_preview(*a, **k)

    def spy_compose(*a, **k):
        threads.append(threading.current_thread())
        return real_compose(*a, **k)

    monkeypatch.setattr(routes, "render_preview", spy_preview)
    monkeypatch.setattr(routes, "compose", spy_compose)
    app.dependency_overrides[get_notifier] = lambda: FakeNotifier(DEV_SINK)
    sub = await _sub(session, "Threaded")
    await client.post("/dashboard/notifications/preview", headers=_HEADERS, data=_form())
    await client.post(f"/dashboard/notifications/{sub.id}/test-send", headers=_HEADERS)
    assert len(threads) == 2
    assert all(t is not threading.main_thread() for t in threads)
