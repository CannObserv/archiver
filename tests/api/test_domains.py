"""Tests for /api/v1/domains endpoints.

Covers:
- GET /domains (list, filter by is_active/archived)
- GET /domains/{name} (200 + 404)
- PATCH /domains/{name} (upsert notes/is_active)
- DELETE /domains/{name} (204 + 409 guard)
- POST /domains/{name}/archive + /restore
- domain_name field on InfoSourceOut
- ?domain_name= filter on GET /info-sources
"""

from __future__ import annotations

import pytest

HEADERS = {"X-API-Key": "test-secret-key"}


# ---------------------------------------------------------------------------
# GET /api/v1/domains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_domains_empty(client):
    resp = await client.get("/api/v1/domains", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_list_domains_returns_created_domain(client):
    await client.patch(
        "/api/v1/domains/listtest.example.com",
        headers=HEADERS,
        json={"notes": "test domain"},
    )
    resp = await client.get("/api/v1/domains", headers=HEADERS)
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["items"]]
    assert "listtest.example.com" in names


@pytest.mark.asyncio
async def test_list_domains_filter_active_only(client):
    await client.patch("/api/v1/domains/active.example.com", headers=HEADERS, json={})
    await client.patch(
        "/api/v1/domains/inactive.example.com", headers=HEADERS, json={"is_active": False}
    )
    resp = await client.get("/api/v1/domains?is_active=true", headers=HEADERS)
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["items"]]
    assert "active.example.com" in names
    assert "inactive.example.com" not in names


# ---------------------------------------------------------------------------
# GET /api/v1/domains/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_domain_404_when_absent(client):
    resp = await client.get("/api/v1/domains/does-not-exist.example.com", headers=HEADERS)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_domain_returns_upserted(client):
    await client.patch(
        "/api/v1/domains/getme.example.com",
        headers=HEADERS,
        json={"notes": "hello"},
    )
    resp = await client.get("/api/v1/domains/getme.example.com", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "getme.example.com"
    assert body["notes"] == "hello"
    assert body["is_active"] is True


# ---------------------------------------------------------------------------
# PATCH /api/v1/domains/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_creates_domain_on_first_call(client):
    resp = await client.patch(
        "/api/v1/domains/newdomain.example.com",
        headers=HEADERS,
        json={"notes": "created via patch"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "newdomain.example.com"
    assert body["notes"] == "created via patch"


@pytest.mark.asyncio
async def test_patch_updates_notes(client):
    await client.patch("/api/v1/domains/update.example.com", headers=HEADERS, json={})
    resp = await client.patch(
        "/api/v1/domains/update.example.com",
        headers=HEADERS,
        json={"notes": "updated notes"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "updated notes"


@pytest.mark.asyncio
async def test_patch_deactivate_domain(client):
    await client.patch("/api/v1/domains/deactivate.example.com", headers=HEADERS, json={})
    resp = await client.patch(
        "/api/v1/domains/deactivate.example.com",
        headers=HEADERS,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# ---------------------------------------------------------------------------
# DELETE /api/v1/domains/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_domain_204(client):
    await client.patch("/api/v1/domains/deleteme.example.com", headers=HEADERS, json={})
    resp = await client.delete("/api/v1/domains/deleteme.example.com", headers=HEADERS)
    assert resp.status_code == 204
    gone = await client.get("/api/v1/domains/deleteme.example.com", headers=HEADERS)
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_delete_domain_409_when_info_sources_exist(client):
    """Cannot delete a domain that has info_sources referencing it."""
    await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "url": "https://nodelete.example.com/path",
            "source_specs": [
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        },
    )
    resp = await client.delete("/api/v1/domains/nodelete.example.com", headers=HEADERS)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST archive / restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_domain(client):
    await client.patch("/api/v1/domains/archive-me.example.com", headers=HEADERS, json={})
    resp = await client.post("/api/v1/domains/archive-me.example.com/archive", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["archived_at"] is not None


@pytest.mark.asyncio
async def test_restore_domain(client):
    await client.patch("/api/v1/domains/restore-me.example.com", headers=HEADERS, json={})
    await client.post("/api/v1/domains/restore-me.example.com/archive", headers=HEADERS)
    resp = await client.post("/api/v1/domains/restore-me.example.com/restore", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None


# ---------------------------------------------------------------------------
# InfoSourceOut domain_name field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_info_source_out_includes_domain_name(client):
    resp = await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "url": "https://domaincheck.example.com/path",
            "source_specs": [
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["domain_name"] == "domaincheck.example.com"


# ---------------------------------------------------------------------------
# GET /info-sources?domain_name= filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_info_sources_filter_by_domain_name(client):
    await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "url": "https://filterdomain.example.com/a",
            "source_specs": [
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        },
    )
    await client.post(
        "/api/v1/info-sources",
        headers=HEADERS,
        json={
            "url": "https://otherdomain.example.com/b",
            "source_specs": [
                {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
            ],
        },
    )
    resp = await client.get(
        "/api/v1/info-sources?domain_name=filterdomain.example.com", headers=HEADERS
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["domain_name"] == "filterdomain.example.com" for i in items)
    assert len(items) >= 1


# ---------------------------------------------------------------------------
# Fetch-policy fields (archiver#360): stored and editable, dark until #366/#364
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_domain_carries_the_default_policy(client):
    resp = await client.patch("/api/v1/domains/policy.example.com", headers=HEADERS, json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_interval_seconds"] == 1.0
    assert body["default_watch_spec"] is None


@pytest.mark.asyncio
async def test_patch_sets_min_interval_and_cadence(client):
    spec = {"schema_version": 1, "interval": "6h"}
    resp = await client.patch(
        "/api/v1/domains/policy.example.com",
        headers=HEADERS,
        json={"min_interval_seconds": 2.5, "default_watch_spec": spec},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["min_interval_seconds"] == 2.5
    assert resp.json()["default_watch_spec"] == spec

    got = (await client.get("/api/v1/domains/policy.example.com", headers=HEADERS)).json()
    assert (got["min_interval_seconds"], got["default_watch_spec"]) == (2.5, spec)


@pytest.mark.asyncio
async def test_patch_omitting_a_field_leaves_it_and_null_clears_the_cadence(client):
    spec = {"schema_version": 1, "interval": "1d"}
    await client.patch(
        "/api/v1/domains/keep.example.com",
        headers=HEADERS,
        json={"min_interval_seconds": 3.0, "default_watch_spec": spec},
    )

    kept = await client.patch(
        "/api/v1/domains/keep.example.com", headers=HEADERS, json={"notes": "n"}
    )
    assert (kept.json()["min_interval_seconds"], kept.json()["default_watch_spec"]) == (3.0, spec)

    cleared = await client.patch(
        "/api/v1/domains/keep.example.com", headers=HEADERS, json={"default_watch_spec": None}
    )
    assert cleared.json()["default_watch_spec"] is None
    assert cleared.json()["min_interval_seconds"] == 3.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        '{"min_interval_seconds": -1}',
        '{"min_interval_seconds": null}',
        '{"min_interval_seconds": Infinity}',
        '{"min_interval_seconds": NaN}',
        '{"min_interval_seconds": "fast"}',
    ],
)
async def test_patch_refuses_a_min_interval_that_is_not_finite_and_non_negative(client, raw):
    resp = await client.patch(
        "/api/v1/domains/bad.example.com",
        headers={**HEADERS, "Content-Type": "application/json"},
        content=raw,
    )
    assert resp.status_code == 422, resp.text
    assert (await client.get("/api/v1/domains/bad.example.com", headers=HEADERS)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spec",
    [
        {"schema_version": 1},  # no interval: NULL is how "no default" is said
        {"schema_version": 1, "interval": "6 hours"},
        {"schema_version": 1, "interval": "6h", "active": False},
        {"schema_version": 2, "interval": "6h"},
        {"interval": "6h"},  # Watcher's ScheduleConfig shape, not a WatchSpec
    ],
)
async def test_patch_refuses_a_cadence_that_is_not_a_watch_spec_with_an_interval(client, spec):
    resp = await client.patch(
        "/api/v1/domains/badspec.example.com",
        headers=HEADERS,
        json={"default_watch_spec": spec},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["kind"] == "schema"
    assert (
        await client.get("/api/v1/domains/badspec.example.com", headers=HEADERS)
    ).status_code == 404


@pytest.mark.asyncio
async def test_patch_racing_a_delete_is_a_409_not_a_500(client, monkeypatch):
    """CR 15: a DELETE committing between the upsert's insert and its row lock."""

    async def _deleted(*args, **kwargs):
        return None

    monkeypatch.setattr("src.api.routes.domains.update_domain", _deleted)
    resp = await client.patch(
        "/api/v1/domains/race.example.com", headers=HEADERS, json={"notes": "n"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["kind"] == "conflict"
