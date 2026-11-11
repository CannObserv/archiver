"""The Capture Policy card on InfoSource detail (archiver#380 slice C).

Covers:
  POST /dashboard/info-sources/{id}/capture-policy
  the #capture-policy-card on GET /dashboard/info-sources/{id}

1. Switch off: no card, the POST 404s and stores nothing
2. The card states the effective policy: the default for none, else the stored one
3. Save: stores the normalized document, swaps the card, flashes, moves focus
4. A refusal swaps the card back at 200 with the error, the input echoed, nothing stored
5. Clear: stores SQL NULL
6. No-JS fallback: 303 on success, full-page 422 on a refusal
"""

from __future__ import annotations

import pytest
from ulid import ULID

from src.core.models import InfoSource
from src.core.services.capture import ENABLED_ENV
from tests.dashboard.conftest import read_flash

_HEADERS = {"X-ExeDev-UserID": "ext-policy", "X-ExeDev-Email": "policy@example.com"}
_HTMX = {**_HEADERS, "HX-Request": "true"}

_FOCUS = 'getElementById("capture-policy-heading")'

_FORM = {
    "width": "390",
    "height": "844",
    "wait_kind": "selector",
    "wait_selector": "#main",
    "wait_seconds": "",
    "on_revision": "on",
}


@pytest.fixture
def capture_on(monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "1")


@pytest.fixture
def capture_off(monkeypatch):
    monkeypatch.delenv(ENABLED_ENV, raising=False)


async def _source(session, policy=None) -> InfoSource:
    source = InfoSource(
        url="https://example.com/policy-page", source_specs=[], capture_policy=policy
    )
    session.add(source)
    await session.flush()
    return source


async def _detail(client, source):
    return await client.get(f"/dashboard/info-sources/{source.info_source_id}", headers=_HEADERS)


async def _save(client, source, form, headers=_HTMX):
    return await client.post(
        f"/dashboard/info-sources/{source.info_source_id}/capture-policy",
        data=form,
        headers=headers,
        follow_redirects=False,
    )


async def _stored(session, source):
    await session.refresh(source)
    return source.capture_policy


def _card(text: str) -> str:
    start = text.index('id="capture-policy-card"')
    return text[start:]


# --- 1. switch off ---


@pytest.mark.asyncio
async def test_switch_off_offers_no_card_and_refuses_the_post(client, session, capture_off):
    source = await _source(session)
    assert 'id="capture-policy-card"' not in (await _detail(client, source)).text
    assert (await _save(client, source, _FORM)).status_code == 404
    assert await _stored(session, source) is None


# --- 2. the effective policy ---


@pytest.mark.asyncio
async def test_no_policy_states_the_default_and_no_revision_captures(client, session, capture_on):
    source = await _source(session)

    card = _card((await _detail(client, source)).text)

    assert "Capture Policy" in card
    assert "1280×800" in card
    assert "full page" in card
    assert "New revisions are not captured" in card
    assert f'hx-post="/dashboard/info-sources/{source.info_source_id}/capture-policy"' in card
    assert 'hx-target="#capture-policy-card"' in card
    # Nothing to clear.
    assert 'value="clear"' not in card


@pytest.mark.asyncio
async def test_a_stored_policy_is_stated_and_prefills_the_form(client, session, capture_on):
    source = await _source(
        session,
        {
            "viewport": {"width": 390, "height": 844},
            "full_page": False,
            "wait": {"kind": "delay", "selector": None, "seconds": 2.5},
            "on_revision": True,
        },
    )

    card = _card((await _detail(client, source)).text)

    assert "390×844" in card
    assert "viewport only" in card
    assert "2.5 s after load" in card
    assert "Each new revision is captured" in card
    assert 'name="width" value="390"' in card
    assert 'name="wait_seconds" value="2.5"' in card
    assert 'value="clear"' in card


# --- 3. save ---


@pytest.mark.asyncio
async def test_save_stores_the_normalized_policy_and_swaps_the_card(client, session, capture_on):
    source = await _source(session)

    r = await _save(client, source, _FORM)

    assert r.status_code == 200
    assert await _stored(session, source) == {
        "viewport": {"width": 390, "height": 844},
        "full_page": False,
        "wait": {"kind": "selector", "selector": "#main", "seconds": None},
        "on_revision": True,
    }
    assert 'id="capture-policy-card"' in r.text
    assert "Source Specification" not in r.text  # the card alone, not the page
    assert "#main" in r.text
    assert "Each new revision is captured" in r.text
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert _FOCUS in r.text


@pytest.mark.asyncio
async def test_full_page_is_a_checkbox(client, session, capture_on):
    source = await _source(session)
    await _save(client, source, {**_FORM, "full_page": "on", "wait_kind": ""})
    stored = await _stored(session, source)
    assert stored["full_page"] is True
    assert stored["wait"] is None


@pytest.mark.asyncio
async def test_network_idle_ignores_the_other_wait_fields(client, session, capture_on):
    source = await _source(session)
    await _save(
        client,
        source,
        {**_FORM, "wait_kind": "networkidle", "wait_selector": "#stale", "wait_seconds": "3"},
    )
    assert (await _stored(session, source))["wait"] == {
        "kind": "networkidle",
        "selector": None,
        "seconds": None,
    }


# --- 4. refusals ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"width": "0"}, "width"),
        ({"height": "5000"}, "height"),
        ({"width": "wide"}, "whole number"),
        ({"wait_kind": "selector", "wait_selector": " "}, "selector"),
        ({"wait_kind": "delay", "wait_seconds": "31"}, "30"),
        ({"wait_kind": "delay", "wait_seconds": "soon"}, "number"),
        ({"wait_kind": "load"}, "wait"),
    ],
)
async def test_a_refusal_swaps_back_with_the_error_and_stores_nothing(
    client, session, capture_on, override, message
):
    source = await _source(session)

    r = await _save(client, source, {**_FORM, **override})

    assert r.status_code == 200
    assert 'role="alert"' in r.text
    assert message in r.text
    assert await _stored(session, source) is None
    # The operator's input survives, and the editor stays open.
    field, value = next(iter(override.items()))
    if field != "wait_kind":
        assert f'value="{value}"' in r.text
    assert "<details open" in r.text
    assert "HX-Trigger" not in r.headers


# --- 5. clear ---


@pytest.mark.asyncio
async def test_clear_removes_the_policy(client, session, capture_on):
    source = await _source(session, {"on_revision": True})

    r = await _save(client, source, {"action": "clear"})

    assert r.status_code == 200
    assert await _stored(session, source) is None
    assert "New revisions are not captured" in r.text
    assert read_flash(r)["showFlash"]["level"] == "success"


# --- 6. no-JS ---


@pytest.mark.asyncio
async def test_plain_post_redirects_on_success(client, session, capture_on):
    source = await _source(session)
    r = await _save(client, source, _FORM, headers=_HEADERS)
    assert r.status_code == 303
    assert r.headers["location"] == f"/dashboard/info-sources/{source.info_source_id}"
    assert (await _stored(session, source))["on_revision"] is True


@pytest.mark.asyncio
async def test_plain_post_rerenders_the_page_at_422_on_a_refusal(client, session, capture_on):
    source = await _source(session)
    r = await _save(client, source, {**_FORM, "width": "0"}, headers=_HEADERS)
    assert r.status_code == 422
    assert "Source Specification" in r.text
    card = _card(r.text)
    assert 'role="alert"' in card
    assert 'name="width" value="0"' in card
    # A full page is not a swap: no focus script steals focus from the error.
    assert _FOCUS not in r.text


@pytest.mark.asyncio
async def test_post_for_an_unknown_source_is_404(client, capture_on):
    r = await client.post(
        f"/dashboard/info-sources/{ULID()}/capture-policy", data=_FORM, headers=_HTMX
    )
    assert r.status_code == 404
