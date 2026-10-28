"""Temporal profiles over the API (archiver#365): one per InfoItem, a singular resource.

``GET`` / ``PUT`` / ``DELETE /info-items/{id}/temporal-profile``. ``PUT`` is a
whole-document create-or-replace; the service behind it is
``tests/core/services/test_temporal_profiles.py``'s, so this pins the HTTP
contract: shapes, status codes, the error envelope, and that the write
evaluates against the real UTC day.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from src.core.models import ChangesOutboxRow

HEADERS = {"X-API-Key": "test-secret-key"}
_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "body"},
    "fingerprint": {},
}
MISSING = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def _today() -> date:
    return datetime.now(UTC).date()


def _event_body(days_out: int = 3, **kw) -> dict:
    return {
        "profile_type": "event",
        "reference_date": (_today() + timedelta(days=days_out)).isoformat(),
        "rules": [{"days_before": 30, "interval": "6h"}, {"days_before": 7, "interval": "1h"}],
        "post_action": "deactivate",
    } | kw


async def _make_item(client) -> str:
    body = {
        "name": "Profiled",
        "initial_url": "https://profile-api.example.com/a",
        "initial_source_specs": [_SPEC],
    }
    resp = await client.post("/api/v1/info-items", headers=HEADERS, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["info_item_id"]


def _url(item_id: str) -> str:
    return f"/api/v1/info-items/{item_id}/temporal-profile"


async def _intervals(session, item_id: str) -> list[str | None]:
    rows = (
        await session.execute(
            select(ChangesOutboxRow.payload).where(ChangesOutboxRow.topic == "info.registry")
        )
    ).scalars()
    mine = sorted((p for p in rows if p["info_item_id"] == item_id), key=lambda p: p["generation"])
    return [p["watch_spec"].get("interval") for p in mine]


@pytest.mark.asyncio
async def test_put_creates_evaluates_today_and_announces(client, session):
    item_id = await _make_item(client)

    resp = await client.put(_url(item_id), headers=HEADERS, json=_event_body())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["info_item_id"] == item_id
    assert body["resolved_interval"] == "1h"
    assert body["evaluated_on"] == _today().isoformat()
    assert body["fired_at"] is None
    assert body["is_active"] is True
    assert body["rules"] == [
        {"days_before": 30, "interval": "6h"},
        {"days_before": 7, "interval": "1h"},
    ]
    assert body["date_range_start"] is None
    assert (await _intervals(session, item_id))[-1] == "1h"


@pytest.mark.asyncio
async def test_get_returns_the_stored_profile(client):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json=_event_body())

    resp = await client.get(_url(item_id), headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["resolved_interval"] == "1h"


@pytest.mark.asyncio
async def test_put_replaces_the_whole_document(client):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json=_event_body())
    seasonal = {
        "profile_type": "seasonal",
        "date_range_start": _today().isoformat(),
        "date_range_end": (_today() + timedelta(days=10)).isoformat(),
        "rules": [{"interval": "2h"}],
        "post_action": "reduce_frequency",
        "is_active": False,
    }

    body = (await client.put(_url(item_id), headers=HEADERS, json=seasonal)).json()

    assert body["profile_type"] == "seasonal"
    assert body["reference_date"] is None
    assert body["rules"] == [{"interval": "2h"}]
    assert body["resolved_interval"] is None  # inactive


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "path"),
    [
        (_event_body(reference_date=None), "reference_date"),
        (_event_body(rules=[{"days_before": 7, "interval": "0h"}]), "rules/0/interval"),
        (
            _event_body(rules=[{"days_before": 7, "interval": "1h"}] * 2),
            "rules/1/days_before",
        ),
        (_event_body(days_out=-1), "reference_date"),  # the window already ended
    ],
)
async def test_an_invalid_profile_is_a_422_envelope_with_paths(client, session, body, path):
    item_id = await _make_item(client)
    before = await _intervals(session, item_id)

    resp = await client.put(_url(item_id), headers=HEADERS, json=body)

    assert resp.status_code == 422, resp.text
    envelope = resp.json()["detail"]
    assert envelope["kind"] == "schema"
    assert path in [e["path"] for e in envelope["errors"]]
    assert (await client.get(_url(item_id), headers=HEADERS)).status_code == 404
    assert await _intervals(session, item_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        _event_body(profile_type="weekly"),
        _event_body(post_action="notify"),
        _event_body(rules=[{"days_before": True, "interval": "1h"}]),
        _event_body(rules=[{"days_before": 7, "interval": "1h", "note": "x"}]),
        _event_body(extra="field"),
    ],
)
async def test_a_malformed_body_is_a_422(client, body):
    item_id = await _make_item(client)

    resp = await client.put(_url(item_id), headers=HEADERS, json=body)

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_delete_removes_it_and_announces_the_tier_below(client, session):
    item_id = await _make_item(client)
    await client.put(_url(item_id), headers=HEADERS, json=_event_body())

    resp = await client.delete(_url(item_id), headers=HEADERS)

    assert resp.status_code == 204
    assert (await client.get(_url(item_id), headers=HEADERS)).status_code == 404
    assert (await _intervals(session, item_id))[-2:] == ["1h", None]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "put", "delete"])
async def test_a_missing_item_is_a_404(client, method):
    kwargs = {"json": _event_body()} if method == "put" else {}

    resp = await getattr(client, method)(_url(MISSING), headers=HEADERS, **kwargs)

    assert resp.status_code == 404
    assert resp.json()["detail"]["message"] == "InfoItem not found"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "delete"])
async def test_an_item_without_a_profile_is_a_404(client, method):
    item_id = await _make_item(client)

    resp = await getattr(client, method)(_url(item_id), headers=HEADERS)

    assert resp.status_code == 404
    assert resp.json()["detail"]["message"] == "TemporalProfile not found"


@pytest.mark.asyncio
async def test_the_routes_require_the_api_key(client):
    item_id = await _make_item(client)

    assert (await client.get(_url(item_id))).status_code == 403
