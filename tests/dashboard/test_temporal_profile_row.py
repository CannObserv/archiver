"""The watch panel's Temporal profile row and its routes (archiver#365).

``POST /dashboard/info-items/{id}/temporal-profile`` saves through the service
the API uses; ``…/temporal-profile/delete`` removes it. Both answer with the
section and ``watcherUpdated``, a refusal as a ``showFlash``, like the cadence
editor, and both share its announceability gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.models import InfoItem, TemporalProfile, WatchStatus
from src.core.services import temporal_profiles

_HEADERS = {"X-ExeDev-UserID": "ext-profile", "X-ExeDev-Email": "profile@example.com"}


def _in(days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def _form(**kw) -> dict:
    return {
        "profile_type": "event",
        "reference_date": _in(3),
        "date_range_start": "",
        "date_range_end": "",
        "rules": "30:6h, 7:1h",
        "post_action": "deactivate",
        "is_active": "on",
    } | kw


async def _watched(session, bind_source, slug: str, *, specs=None) -> InfoItem:
    item = InfoItem(name=slug, watch_spec={"schema_version": 1, "interval": "1d"})
    session.add(item)
    await session.flush()
    await bind_source(session, item, slug=slug, specs=specs)
    session.add(
        WatchStatus(
            info_item_id=item.info_item_id,
            applied_generation=item.announcement_generation,
            applied_active=True,
            applied_interval="1d",
            last_attempt_at=datetime.now(UTC),
            last_observed_at=datetime.now(UTC),
            health="ok",
            occurred_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return item


def _url(item: InfoItem, suffix: str = "") -> str:
    return f"/dashboard/info-items/{item.info_item_id}/temporal-profile{suffix}"


async def _section(client, item: InfoItem) -> str:
    r = await client.get(
        f"/dashboard/info-items/{item.info_item_id}/watcher-section", headers=_HEADERS
    )
    assert r.status_code == 200
    return r.text


@pytest.mark.asyncio
async def test_the_row_offers_a_profile_when_there_is_none(client, session, bind_source):
    item = await _watched(session, bind_source, "row-none")

    html = await _section(client, item)

    assert "Temporal profile" in html
    assert "No profile" in html
    assert f'hx-post="{_url(item)}"' in html
    assert "/delete" not in html


@pytest.mark.asyncio
async def test_saving_stores_announces_and_names_the_profile_tier(client, session, bind_source):
    item = await _watched(session, bind_source, "row-save")

    r = await client.post(_url(item), headers=_HEADERS, data=_form())

    assert r.status_code == 200
    assert "watcherUpdated" in r.headers["HX-Trigger"]
    assert "showFlash" not in r.headers["HX-Trigger"]
    profile = await session.get(TemporalProfile, item.info_item_id)
    assert profile.resolved_interval == "1h"
    html = await _section(client, item)
    assert "Event on" in html and "Now Hourly" in html
    assert ">profile<" in html  # the Cadence cell names the winning tier
    assert (
        f'action="{_url(item, "/delete")}"' in html or f'hx-post="{_url(item, "/delete")}"' in html
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("form", "said"),
    [
        (_form(reference_date=_in(-1)), "the window ended"),
        (_form(rules="7:0h"), "greater than zero"),
        (_form(rules="seven:1h"), "days_before:interval"),
        (_form(reference_date=""), "reference_date"),
    ],
)
async def test_a_refusal_flashes_and_stores_nothing(client, session, bind_source, form, said):
    item = await _watched(session, bind_source, "row-refuse-" + said.replace(" ", "-"))

    r = await client.post(_url(item), headers=_HEADERS, data=form)

    assert r.status_code == 200
    assert "showFlash" in r.headers["HX-Trigger"]
    assert said in r.headers["HX-Trigger"]
    assert await session.get(TemporalProfile, item.info_item_id) is None


@pytest.mark.asyncio
async def test_an_unannounceable_item_is_refused(client, session, bind_source):
    item = await _watched(session, bind_source, "row-unannounceable", specs=[])

    r = await client.post(_url(item), headers=_HEADERS, data=_form())

    assert "showFlash" in r.headers["HX-Trigger"]
    assert await session.get(TemporalProfile, item.info_item_id) is None


@pytest.mark.asyncio
async def test_delete_removes_the_profile(client, session, bind_source):
    item = await _watched(session, bind_source, "row-delete")
    await client.post(_url(item), headers=_HEADERS, data=_form())

    r = await client.post(_url(item, "/delete"), headers=_HEADERS)

    assert r.status_code == 200
    assert "watcherUpdated" in r.headers["HX-Trigger"]
    assert await session.get(TemporalProfile, item.info_item_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/delete"])
async def test_a_failed_write_degrades_the_panel_instead_of_a_500(
    client, session, bind_source, monkeypatch, suffix
):
    """CR 1: the cadence editor's contract - roll back, flash, render degraded."""
    item = await _watched(session, bind_source, f"row-fail{suffix.replace('/', '-')}")

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(temporal_profiles, "put_temporal_profile", _boom)
    monkeypatch.setattr(temporal_profiles, "delete_temporal_profile", _boom)

    r = await client.post(_url(item, suffix), headers=_HEADERS, data=_form())

    assert r.status_code == 200
    assert "showFlash" in r.headers["HX-Trigger"]
    assert "Couldn't update this item" in r.text
