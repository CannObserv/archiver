"""respx-mocked tests for ArchiverClient v2 endpoints."""

import httpx
import pytest
import respx
from archiver_client import (
    AuthError,
    NotFound,
    ValidationError,
)

BASE_URL = "http://archiver.test"

_TS = "2026-05-04T00:00:00Z"


def _info_item_payload(info_item_id: str = "01HZZ00000000000000000000A") -> dict:
    return {
        "info_item_id": info_item_id,
        "name": "X",
        "description": None,
        "owner": None,
        "rep_fields": {},
        "created_at": _TS,
        "updated_at": _TS,
    }


def _rep_spec_out_payload(
    assignment_id: str = "01HZZ00000000000000000000C",
    rep_spec_id: str = "01HZZ00000000000000000000D",
) -> dict:
    return {
        "id": assignment_id,
        "rep_spec_id": rep_spec_id,
        "activated_at": _TS,
        "deactivated_at": None,
        "public_url": None,
    }


def _source_revision_payload(
    source_revision_id: str = "01HZZ00000000000000000000E",
    info_source_id: str = "01HZZ00000000000000000000F",
) -> dict:
    return {
        "source_revision_id": source_revision_id,
        "info_source_id": info_source_id,
        "content_fingerprint": "sha256:abc",
        "captured_at": _TS,
        "content_cache_uri": None,
        "content_cache_expires_at": None,
        "content_media_type": None,
        "content_size_bytes": None,
    }


def _source_revision_binding_payload() -> dict:
    return {
        "info_item_id": "01HZZ00000000000000000000A",
        "source_revision_id": "01HZZ00000000000000000000E",
        "bound_at": _TS,
    }


def _info_item_source_out_payload(
    info_source_id: str = "01HZZ00000000000000000000F",
    *,
    is_active: bool = True,
    deactivated_at: str | None = None,
) -> dict:
    return {
        "info_source_id": info_source_id,
        "is_active": is_active,
        "created_at": _TS,
        "deactivated_at": deactivated_at,
    }


def _top_info_source_payload(
    info_source_id: str = "01HZZ00000000000000000000F",
    url: str = "https://example.com/p",
    source_specs: list | None = None,
) -> dict:
    return {
        "info_source_id": info_source_id,
        "url": url,
        "source_specs": source_specs
        if source_specs is not None
        else [{"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}],
        "created_at": _TS,
    }


# --- InfoItem endpoints ---


@pytest.mark.asyncio
async def test_create_info_item(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/info-items").mock(
            return_value=httpx.Response(201, json=_info_item_payload())
        )
        out = await client.create_info_item(name="X")
    assert out.name == "X"
    assert out.rep_fields is not None


@pytest.mark.asyncio
async def test_get_info_item(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A").mock(
            return_value=httpx.Response(200, json=_info_item_payload())
        )
        out = await client.get_info_item("01HZZ00000000000000000000A")
    assert out.name == "X"
    assert str(out.info_item_id) == "01HZZ00000000000000000000A"


@pytest.mark.asyncio
async def test_list_info_items(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        _info_item_payload("01HZZ00000000000000000000A"),
                        _info_item_payload("01HZZ00000000000000000000B"),
                    ],
                    "has_more": False,
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        out = await client.list_info_items()
    assert out.has_more is False
    assert out.limit == 100
    assert out.offset == 0
    assert len(out.items) == 2
    assert out.items[0].name == "X"


@pytest.mark.asyncio
async def test_list_info_items_forwards_pagination_params(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-items").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_info_item_payload("01HZZ00000000000000000000A")],
                    "has_more": True,
                    "limit": 1,
                    "offset": 2,
                },
            )
        )
        out = await client.list_info_items(limit=1, offset=2)
    assert route.calls.last.request.url.params.get("limit") == "1"
    assert route.calls.last.request.url.params.get("offset") == "2"
    assert out.has_more is True
    assert out.limit == 1
    assert out.offset == 2


@pytest.mark.asyncio
async def test_get_info_item_404_raises_not_found(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/missing").mock(
            return_value=httpx.Response(
                404,
                json={
                    "detail": {
                        "kind": "lookup",
                        "message": "InfoItem not found",
                        "errors": [],
                    }
                },
            )
        )
        with pytest.raises(NotFound):
            await client.get_info_item("missing")


@pytest.mark.asyncio
async def test_get_info_item_401_raises_auth_error(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/x").mock(
            return_value=httpx.Response(
                401,
                json={
                    "detail": {
                        "kind": "auth",
                        "message": "Invalid API key",
                        "errors": [],
                    }
                },
            )
        )
        with pytest.raises(AuthError):
            await client.get_info_item("x")


@pytest.mark.asyncio
async def test_get_info_item_422_raises_validation_error(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/bad-id").mock(
            return_value=httpx.Response(
                422,
                json={
                    "detail": {
                        "kind": "domain",
                        "message": "info_item_id is not a valid ULID",
                        "errors": [
                            {
                                "path": "/info_item_id",
                                "message": "not a valid ULID",
                                "code": "invalid_ulid",
                            }
                        ],
                    }
                },
            )
        )
        with pytest.raises(ValidationError):
            await client.get_info_item("bad-id")


@pytest.mark.asyncio
async def test_get_info_item_include_deactivated_forwards_param(client):
    """include_deactivated=True must be forwarded as a query param."""
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A").mock(
            return_value=httpx.Response(200, json=_info_item_payload())
        )
        await client.get_info_item("01HZZ00000000000000000000A", include_deactivated=True)
    assert route.calls.last.request.url.params.get("include_deactivated") == "true"


@pytest.mark.asyncio
async def test_deactivate_info_source_binding(client):
    """Happy path: returns deactivated InfoItemSourceOut with is_active=False."""
    payload = _info_item_source_out_payload(is_active=False, deactivated_at=_TS)
    with respx.mock:
        respx.delete(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A"
            f"/info-sources/01HZZ00000000000000000000F"
        ).mock(return_value=httpx.Response(200, json=payload))
        out = await client.deactivate_info_source_binding(
            "01HZZ00000000000000000000A", "01HZZ00000000000000000000F"
        )
    assert out.is_active is False
    assert out.deactivated_at is not None


@pytest.mark.asyncio
async def test_deactivate_info_source_binding_404_raises_not_found(client):
    with respx.mock:
        respx.delete(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/info-sources/missing"
        ).mock(
            return_value=httpx.Response(
                404,
                json={
                    "detail": {
                        "kind": "lookup",
                        "message": "Active binding not found",
                        "errors": [],
                    }
                },
            )
        )
        with pytest.raises(NotFound):
            await client.deactivate_info_source_binding("01HZZ00000000000000000000A", "missing")


# --- RepSpec assignment endpoints ---


@pytest.mark.asyncio
async def test_assign_rep_spec(client):
    with respx.mock:
        respx.post(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/rep-spec-assignments"
        ).mock(return_value=httpx.Response(201, json=_rep_spec_out_payload()))
        out = await client.assign_rep_spec(
            "01HZZ00000000000000000000A", "01HZZ00000000000000000000D"
        )
    assert out.rep_spec_id == "01HZZ00000000000000000000D"
    assert out.deactivated_at is None


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment(client):
    with respx.mock:
        respx.delete(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/rep-spec-assignments/01HZZ00000000000000000000C"
        ).mock(return_value=httpx.Response(204))
        result = await client.deactivate_rep_spec_assignment(
            "01HZZ00000000000000000000A", "01HZZ00000000000000000000C"
        )
    assert result is None


@pytest.mark.asyncio
async def test_deactivate_rep_spec_assignment_404_raises_not_found(client):
    with respx.mock:
        respx.delete(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/rep-spec-assignments/missing"
        ).mock(
            return_value=httpx.Response(
                404,
                json={
                    "detail": {
                        "kind": "lookup",
                        "message": "RepSpec assignment not found",
                        "errors": [],
                    }
                },
            )
        )
        with pytest.raises(NotFound):
            await client.deactivate_rep_spec_assignment("01HZZ00000000000000000000A", "missing")


@pytest.mark.asyncio
async def test_set_public_url(client):
    payload = _rep_spec_out_payload()
    payload["public_url"] = "https://s3.example.com/replicated/foo.pdf"
    with respx.mock:
        respx.patch(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/rep-spec-assignments/01HZZ00000000000000000000C"
        ).mock(return_value=httpx.Response(200, json=payload))
        out = await client.set_public_url(
            "01HZZ00000000000000000000A",
            "01HZZ00000000000000000000C",
            "https://s3.example.com/replicated/foo.pdf",
        )
    assert out.public_url == "https://s3.example.com/replicated/foo.pdf"


# --- InfoSource binding ---


@pytest.mark.asyncio
async def test_add_info_source(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/info-sources").mock(
            return_value=httpx.Response(201, json=_info_item_source_out_payload())
        )
        out = await client.add_info_source(
            "01HZZ00000000000000000000A",
            "01HZZ00000000000000000000F",
        )
    assert out.info_source_id == "01HZZ00000000000000000000F"
    assert out.is_active is True


# --- SourceRevision endpoints ---


@pytest.mark.asyncio
async def test_post_source_revision(client):
    import datetime

    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/source-revisions").mock(
            return_value=httpx.Response(201, json=_source_revision_payload())
        )
        out = await client.post_source_revision(
            info_source_id="01HZZ00000000000000000000F",
            content_fingerprint="sha256:abc",
            captured_at=datetime.datetime(2026, 5, 4, tzinfo=datetime.UTC),
        )
    assert out.content_fingerprint == "sha256:abc"
    assert out.source_revision_id == "01HZZ00000000000000000000E"


@pytest.mark.asyncio
async def test_post_source_revision_with_client_supplied_ulid(client):
    """Client-supplied source_revision_id is forwarded in the request body."""
    import datetime
    import json

    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/source-revisions").mock(
            return_value=httpx.Response(201, json=_source_revision_payload())
        )
        await client.post_source_revision(
            info_source_id="01HZZ00000000000000000000F",
            content_fingerprint="sha256:abc",
            captured_at=datetime.datetime(2026, 5, 4, tzinfo=datetime.UTC),
            source_revision_id="01JV0000000000000000000000",
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["source_revision_id"] == "01JV0000000000000000000000"


@pytest.mark.asyncio
async def test_patch_source_revision_cache(client):
    payload = _source_revision_payload()
    payload["content_cache_uri"] = "s3://bucket/key"
    with respx.mock:
        respx.patch(f"{BASE_URL}/api/v1/source-revisions/01HZZ00000000000000000000E").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = await client.patch_source_revision_cache(
            "01HZZ00000000000000000000E",
            content_cache_uri="s3://bucket/key",
        )
    assert out.content_cache_uri == "s3://bucket/key"


# --- Bind revision ---


@pytest.mark.asyncio
async def test_bind_revision(client):
    with respx.mock:
        respx.post(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/source-revisions"
        ).mock(return_value=httpx.Response(201, json=_source_revision_binding_payload()))
        out = await client.bind_revision(
            "01HZZ00000000000000000000A",
            "01HZZ00000000000000000000E",
        )
    assert out.source_revision_id == "01HZZ00000000000000000000E"
    assert out.info_item_id == "01HZZ00000000000000000000A"


# --- Top-level InfoSource endpoints ---


@pytest.mark.asyncio
async def test_create_info_source(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(201, json=_top_info_source_payload()),
        )
        out = await client.create_info_source(
            "https://example.com/p",
            [{"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}],
        )
    sent_body = route.calls[0].request.read()
    assert b'"url"' in sent_body
    assert b'"source_specs"' in sent_body
    assert out.url == "https://example.com/p"
    assert len(out.source_specs) == 1


@pytest.mark.asyncio
async def test_get_info_source(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-sources/01HZZ00000000000000000000F").mock(
            return_value=httpx.Response(200, json=_top_info_source_payload())
        )
        out = await client.get_info_source("01HZZ00000000000000000000F")
    assert out.info_source_id == "01HZZ00000000000000000000F"


@pytest.mark.asyncio
async def test_list_info_sources_no_filter(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_top_info_source_payload()],
                    "has_more": False,
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        out = await client.list_info_sources()
    assert out.has_more is False
    assert out.limit == 100
    assert out.offset == 0
    assert len(out.items) == 1
    # No query string when filter is omitted
    assert b"url" not in route.calls[0].request.url.query


@pytest.mark.asyncio
async def test_list_info_sources_filter_by_url(client):
    filter_url = "https://example.com/filter"
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_top_info_source_payload(url=filter_url)],
                    "has_more": False,
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        out = await client.list_info_sources(url=filter_url)
    assert len(out.items) == 1
    assert out.items[0].url == filter_url
    assert b"url" in route.calls[0].request.url.query


@pytest.mark.asyncio
async def test_list_info_sources_forwards_pagination_params(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_top_info_source_payload()],
                    "has_more": True,
                    "limit": 1,
                    "offset": 4,
                },
            )
        )
        out = await client.list_info_sources(limit=1, offset=4)
    assert route.calls.last.request.url.params.get("limit") == "1"
    assert route.calls.last.request.url.params.get("offset") == "4"
    assert out.has_more is True


@pytest.mark.asyncio
async def test_update_info_source_specs(client):
    new_specs = [
        {
            "schema_version": 1,
            "extraction": {"algorithm": "css", "selector": "#main"},
            "fingerprint": {},
        }
    ]
    with respx.mock:
        route = respx.patch(
            f"{BASE_URL}/api/v1/info-sources/01HZZ00000000000000000000F/source-specs"
        ).mock(
            return_value=httpx.Response(200, json=_top_info_source_payload(source_specs=new_specs)),
        )
        out = await client.update_info_source_specs("01HZZ00000000000000000000F", new_specs)
    sent_body = route.calls[0].request.read()
    assert b'"source_specs"' in sent_body
    assert out.source_specs == new_specs


@pytest.mark.asyncio
async def test_update_info_source_specs_not_found_raises(client):
    with respx.mock:
        respx.patch(f"{BASE_URL}/api/v1/info-sources/01HZZ00000000000000000000F/source-specs").mock(
            return_value=httpx.Response(
                404,
                json={
                    "detail": {
                        "kind": "lookup",
                        "message": "InfoSource not found",
                        "errors": [],
                        "data": {},
                    }
                },
            )
        )
        with pytest.raises(NotFound):
            await client.update_info_source_specs(
                "01HZZ00000000000000000000F",
                [
                    {
                        "schema_version": 1,
                        "extraction": {"algorithm": "full_page"},
                        "fingerprint": {},
                    }
                ],
            )
