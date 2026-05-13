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


def _info_source_out_payload() -> dict:
    return {
        "info_source_id": "01HZZ00000000000000000000F",
        "role": "primary",
        "created_at": _TS,
    }


def _top_info_source_payload(
    info_source_id: str = "01HZZ00000000000000000000F",
    parent: str | None = None,
    url: str | None = "https://example.com/p",
) -> dict:
    return {
        "info_source_id": info_source_id,
        "parent_info_source_id": parent,
        "source_spec": {
            "schema_version": 1,
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        "schema_version": 1,
        "url": url,
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
            return_value=httpx.Response(201, json=_info_source_out_payload())
        )
        out = await client.add_info_source(
            "01HZZ00000000000000000000A",
            "01HZZ00000000000000000000F",
            "primary",
        )
    assert out.role == "primary"
    assert out.info_source_id == "01HZZ00000000000000000000F"


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
async def test_create_info_source_root(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(201, json=_top_info_source_payload()),
        )
        out = await client.create_info_source(
            {
                "schema_version": 1,
                "target": {"url": "https://example.com/p"},
                "extraction": {"algorithm": "full_page"},
                "fingerprint": {},
            }
        )
    sent_body = route.calls[0].request.read()
    assert b'"source_spec"' in sent_body
    assert b'"parent_info_source_id"' not in sent_body
    assert out.url == "https://example.com/p"
    assert out.parent_info_source_id is None


@pytest.mark.asyncio
async def test_create_info_source_fragment(client):
    parent_id = "01HZZ00000000000000000000P"
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(
                201,
                json=_top_info_source_payload(parent=parent_id, url=None),
            ),
        )
        out = await client.create_info_source(
            {
                "schema_version": 1,
                "extraction": {"algorithm": "css", "selector": "#x"},
                "fingerprint": {},
            },
            parent_info_source_id=parent_id,
        )
    sent_body = route.calls[0].request.read()
    assert parent_id.encode() in sent_body
    assert out.parent_info_source_id == parent_id
    assert out.url is None


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
    assert b"parent_info_source_id" not in route.calls[0].request.url.query


@pytest.mark.asyncio
async def test_list_info_sources_filter_by_parent(client):
    parent_id = "01HZZ00000000000000000000P"
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/info-sources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_top_info_source_payload(parent=parent_id, url=None)],
                    "has_more": False,
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        out = await client.list_info_sources(parent_info_source_id=parent_id)
    assert len(out.items) == 1
    assert out.items[0].parent_info_source_id == parent_id
    assert parent_id.encode() in route.calls[0].request.url.query


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
