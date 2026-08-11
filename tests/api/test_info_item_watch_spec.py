"""WatchSpec + watch-active read/write surface on InfoItem (archiver#150).

Two routes, deliberately. ``PUT /watch-spec`` replaces the cadence document
whole — that is what makes "no interval" (consumer applies its default)
expressible. ``PUT /watch-active`` carries the single boolean. Folding ``active``
into the document body would have put a replace rule and a merge rule in one
payload, and would have made every dashboard pause a read-modify-write of a
document it does not otherwise touch.
"""

import pytest
from ulid import ULID

HEADERS = {"X-API-Key": "test-secret-key"}

DEFAULT = {"schema_version": 1}


async def _make_item(client, name: str = "Item") -> str:
    return (await client.post("/api/v1/info-items", headers=HEADERS, json={"name": name})).json()[
        "info_item_id"
    ]


# ---------------------------------------------------------------------------
# Read surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_info_item_returns_the_default_watch_spec(client):
    item_id = await _make_item(client)
    response = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["watch_spec"] == DEFAULT


@pytest.mark.asyncio
async def test_get_info_item_returns_null_watch_active_before_the_import(client):
    """Null is "no opinion yet" — distinct from paused and from scheduled."""
    item_id = await _make_item(client)
    response = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert response.json()["watch_active"] is None


# ---------------------------------------------------------------------------
# PUT /{id}/watch-spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_watch_spec_replaces_the_document(client):
    item_id = await _make_item(client)
    doc = {"schema_version": 1, "interval": "6h"}

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": doc}
    )

    assert response.status_code == 200
    assert response.json()["watch_spec"] == doc
    reread = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert reread.json()["watch_spec"] == doc


@pytest.mark.asyncio
async def test_put_watch_spec_accepts_a_document_without_an_interval(client):
    """Absent interval is the way to say 'consumer applies its default'."""
    item_id = await _make_item(client)

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": DEFAULT}
    )

    assert response.status_code == 200
    assert "interval" not in response.json()["watch_spec"]


@pytest.mark.asyncio
async def test_put_watch_spec_clears_a_previously_set_interval(client):
    """PUT replaces the whole document — it is not a merge."""
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "1h"}},
    )

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": DEFAULT}
    )

    assert response.status_code == 200
    assert response.json()["watch_spec"] == DEFAULT


@pytest.mark.asyncio
async def test_put_watch_spec_rejects_a_document_carrying_active(client):
    """A pre-rework client must fail loudly, not lose the operator's pause.

    ``watch_spec`` is an untyped dict on the announcement, so a nested ``active``
    validates cleanly there while the envelope reports "no opinion yet" — this
    422 is the only thing standing between that and a paused item being
    announced as scheduled.
    """
    item_id = await _make_item(client)

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "active": False, "interval": "6h"}},
    )

    assert response.status_code == 422
    assert any("active" in e["message"] for e in response.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_put_watch_spec_rejects_an_invalid_document_with_422_envelope(client):
    item_id = await _make_item(client)

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "daily"}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "schema"
    assert any(e["path"] == "/interval" for e in detail["errors"])


@pytest.mark.asyncio
async def test_put_watch_spec_leaves_the_stored_document_untouched_when_invalid(client):
    item_id = await _make_item(client)
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"schema_version": 1, "interval": "7d"}},
    )

    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": {"interval": "1h"}},
    )

    reread = await client.get(f"/api/v1/info-items/{item_id}", headers=HEADERS)
    assert reread.json()["watch_spec"] == {"schema_version": 1, "interval": "7d"}


@pytest.mark.asyncio
async def test_put_watch_spec_rejects_unknown_body_keys(client):
    """extra='forbid' — a caller reaching for merge semantics gets told, not ignored."""
    item_id = await _make_item(client)

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers=HEADERS,
        json={"document": DEFAULT, "merge": True},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_watch_spec_404s_for_an_unknown_item(client):
    response = await client.put(
        f"/api/v1/info-items/{ULID()}/watch-spec",
        headers=HEADERS,
        json={"document": DEFAULT},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_put_watch_spec_requires_an_api_key(client):
    """Missing key is 403, matching tests/api/test_auth.py; a wrong key is 401."""
    item_id = await _make_item(client)

    missing = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", json={"document": DEFAULT}
    )
    wrong = await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec",
        headers={"X-API-Key": "nope"},
        json={"document": DEFAULT},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 401


# ---------------------------------------------------------------------------
# PUT /{id}/watch-active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_watch_active_pauses_and_resumes(client):
    item_id = await _make_item(client)

    paused = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": False}
    )
    assert paused.status_code == 200
    assert paused.json()["watch_active"] is False

    resumed = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": True}
    )
    assert resumed.json()["watch_active"] is True


@pytest.mark.asyncio
async def test_put_watch_active_is_idempotent(client):
    item_id = await _make_item(client)
    for _ in range(2):
        response = await client.put(
            f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": False}
        )
        assert response.json()["watch_active"] is False


@pytest.mark.asyncio
async def test_put_watch_active_does_not_touch_the_cadence_document(client):
    """The whole point of the split: pausing is not a read-modify-write."""
    item_id = await _make_item(client)
    doc = {"schema_version": 1, "interval": "7d"}
    await client.put(
        f"/api/v1/info-items/{item_id}/watch-spec", headers=HEADERS, json={"document": doc}
    )

    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": False}
    )

    assert response.json()["watch_spec"] == doc


@pytest.mark.asyncio
async def test_put_watch_active_requires_the_field(client):
    """No absence rule at all — null is reachable only by never having written."""
    item_id = await _make_item(client)
    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_watch_active_rejects_an_explicit_null(client):
    item_id = await _make_item(client)
    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active", headers=HEADERS, json={"active": None}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_watch_active_rejects_unknown_body_keys(client):
    item_id = await _make_item(client)
    response = await client.put(
        f"/api/v1/info-items/{item_id}/watch-active",
        headers=HEADERS,
        json={"active": True, "document": DEFAULT},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_watch_active_404s_for_an_unknown_item(client):
    response = await client.put(
        f"/api/v1/info-items/{ULID()}/watch-active", headers=HEADERS, json={"active": True}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_put_watch_active_requires_an_api_key(client):
    item_id = await _make_item(client)
    missing = await client.put(f"/api/v1/info-items/{item_id}/watch-active", json={"active": True})
    assert missing.status_code == 403
