"""The Power Map adapter's status mapping, over a mocked transport (archiver#304).

The SDK returns a ``Response`` for every documented status and ``None``-parsed
for the rest; turning that into ``Snapshot | NotModified | Merged | Gone`` or a
typed "unavailable" is the adapter's whole job. CI never calls live Power Map.
"""

from datetime import UTC, datetime

import httpx
import pytest

from src.core.power_map import (
    DEFAULT_BASE_URL,
    Gone,
    Merged,
    NotModified,
    OrgHit,
    PowerMapClient,
    PowerMapUnavailableError,
    Snapshot,
    power_map_from_env,
)

ORG_ID = "01JPM00000000000000000000A"
WINNER_ID = "01JPM00000000000000000000B"


def _org_body(**overrides) -> dict:
    body = {
        "id": ORG_ID,
        "lifespan": {"start": None, "end": None},
        "active": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-09-30T12:00:00Z",
        "name": "Washington State Liquor and Cannabis Board",
        "acronym": "WSLCB",
        "slug": "wslcb",
        "archived_at": None,
        "succeeded_by": None,
    }
    body.update(overrides)
    return body


def _client(handler) -> PowerMapClient:
    return PowerMapClient("https://pm.test", "k3y", transport=httpx.MockTransport(handler))


async def test_200_is_a_snapshot_carrying_the_etag():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("x-api-key")
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_org_body(), headers={"ETag": '"v7"'})

    result = await _client(handler).get_org(ORG_ID)

    assert isinstance(result, Snapshot)
    org = result.org
    assert org.pm_org_id == ORG_ID
    assert org.name == "Washington State Liquor and Cannabis Board"
    assert org.acronym == "WSLCB"
    assert org.active is True
    assert org.archived_at is None
    assert org.succeeded_by is None
    assert org.pm_updated_at == datetime(2026, 9, 30, 12, tzinfo=UTC)
    assert org.etag == '"v7"'
    # connect(): X-API-Key, never the generated default's Bearer header.
    assert seen == {"path": f"/api/v1/orgs/{ORG_ID}", "key": "k3y", "auth": None}


async def test_200_without_acronym_or_etag_maps_to_none():
    def handler(request):
        return httpx.Response(200, json=_org_body(acronym=None))

    result = await _client(handler).get_org(ORG_ID)

    assert isinstance(result, Snapshot)
    assert result.org.acronym is None
    assert result.org.etag is None


async def test_a_conditional_get_sends_if_none_match_and_304_is_not_modified():
    seen: dict = {}

    def handler(request):
        seen["inm"] = request.headers.get("if-none-match")
        return httpx.Response(304)

    result = await _client(handler).get_org(ORG_ID, etag='"v7"')

    assert isinstance(result, NotModified)
    assert seen["inm"] == '"v7"'


async def test_410_with_merged_into_is_merged():
    def handler(request):
        body = {
            "id": ORG_ID,
            "entity_type": "organization",
            "deleted_at": "2026-10-01T00:00:00Z",
            "merged_into": WINNER_ID,
        }
        return httpx.Response(410, json=body)

    result = await _client(handler).get_org(ORG_ID)

    assert result == Merged(winner=WINNER_ID)


async def test_410_with_null_merged_into_is_gone():
    def handler(request):
        body = {
            "id": ORG_ID,
            "entity_type": "organization",
            "deleted_at": "2026-10-01T00:00:00Z",
            "merged_into": None,
        }
        return httpx.Response(410, json=body)

    assert isinstance(await _client(handler).get_org(ORG_ID), Gone)


async def test_404_is_gone():
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})

    assert isinstance(await _client(handler).get_org(ORG_ID), Gone)


async def test_429_is_unavailable_and_carries_retry_after():
    def handler(request):
        return httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "7"})

    with pytest.raises(PowerMapUnavailableError) as exc:
        await _client(handler).get_org(ORG_ID)

    assert exc.value.retry_after == 7.0
    assert "429" in exc.value.reason


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_unavailable(status):
    def handler(request):
        return httpx.Response(status, text="upstream sad")

    with pytest.raises(PowerMapUnavailableError) as exc:
        await _client(handler).get_org(ORG_ID)

    assert str(status) in exc.value.reason
    assert exc.value.retry_after is None


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_key_is_unavailable(status):
    def handler(request):
        return httpx.Response(status, json={"detail": "no"})

    with pytest.raises(PowerMapUnavailableError) as exc:
        await _client(handler).get_org(ORG_ID)

    assert "API key" in exc.value.reason


async def test_a_timeout_is_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PowerMapUnavailableError) as exc:
        await _client(handler).get_org(ORG_ID)

    assert "timed out" in exc.value.reason


async def test_a_connection_error_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(PowerMapUnavailableError):
        await _client(handler).get_org(ORG_ID)


async def test_a_200_that_is_not_an_org_is_unavailable():
    def handler(request):
        return httpx.Response(200, text="<html>proxy login</html>")

    with pytest.raises(PowerMapUnavailableError):
        await _client(handler).get_org(ORG_ID)


async def test_search_orgs_returns_plain_hits_excluding_archived():
    seen: dict = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        body = {
            "data": [
                {
                    "id": ORG_ID,
                    "lifespan": {"start": None, "end": None},
                    "name": "Washington State Liquor and Cannabis Board",
                    "acronym": "WSLCB",
                },
                {"id": WINNER_ID, "lifespan": {"start": None, "end": None}, "name": None},
            ],
            "meta": {"limit": 10, "offset": 0, "count": 2, "has_more": False},
        }
        return httpx.Response(200, json=body)

    hits = await _client(handler).search_orgs("liquor", limit=10)

    assert hits == [
        OrgHit(
            pm_org_id=ORG_ID,
            name="Washington State Liquor and Cannabis Board",
            acronym="WSLCB",
            archived_at=None,
            succeeded_by=None,
        ),
        OrgHit(pm_org_id=WINNER_ID, name=None, acronym=None, archived_at=None, succeeded_by=None),
    ]
    assert seen["params"]["q"] == "liquor"
    assert seen["params"]["limit"] == "10"
    assert seen["params"]["include_archived"] == "false"


async def test_search_orgs_429_is_unavailable():
    def handler(request):
        return httpx.Response(429, json={"detail": "slow down"})

    with pytest.raises(PowerMapUnavailableError):
        await _client(handler).search_orgs("liquor")


def test_from_env_is_dormant_without_a_key(monkeypatch):
    monkeypatch.delenv("ARCHIVER_POWER_MAP_API_KEY", raising=False)
    assert power_map_from_env() is None
    monkeypatch.setenv("ARCHIVER_POWER_MAP_API_KEY", "  ")
    assert power_map_from_env() is None
    monkeypatch.delenv("ARCHIVER_POWER_MAP_API_KEY")
    monkeypatch.setenv("ARCHIVER_POWER_MAP_BASE_URL", "https://pm.test")
    assert power_map_from_env() is None


def test_from_env_defaults_the_base_url(monkeypatch):
    monkeypatch.setenv("ARCHIVER_POWER_MAP_API_KEY", "k3y")
    monkeypatch.delenv("ARCHIVER_POWER_MAP_BASE_URL", raising=False)
    client = power_map_from_env()
    assert client is not None
    assert client.base_url == DEFAULT_BASE_URL == "https://power-map.exe.xyz"


def test_from_env_honours_a_base_url_override(monkeypatch):
    monkeypatch.setenv("ARCHIVER_POWER_MAP_API_KEY", "k3y")
    monkeypatch.setenv("ARCHIVER_POWER_MAP_BASE_URL", "https://pm.test/")
    client = power_map_from_env()
    assert client is not None
    assert client.base_url == "https://pm.test"


@pytest.mark.parametrize("value", ["nan", "inf", "-5", "Wed, 21 Oct 2026 07:28:00 GMT"])
async def test_a_malformed_retry_after_is_dropped(value):
    """CR 4: the route rounds retry_after into a header; nan/inf would 500 it."""

    def handler(request):
        return httpx.Response(429, json={"detail": "slow"}, headers={"Retry-After": value})

    with pytest.raises(PowerMapUnavailableError) as exc:
        await _client(handler).get_org(ORG_ID)

    assert exc.value.retry_after is None
