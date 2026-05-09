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
                json=[
                    _info_item_payload("01HZZ00000000000000000000A"),
                    _info_item_payload("01HZZ00000000000000000000B"),
                ],
            )
        )
        out = await client.list_info_items()
    assert len(out) == 2
    assert out[0].name == "X"


@pytest.mark.asyncio
async def test_get_info_item_404_raises_not_found(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/missing").mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )
        with pytest.raises(NotFound):
            await client.get_info_item("missing")


@pytest.mark.asyncio
async def test_get_info_item_401_raises_auth_error(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/info-items/x").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorized"})
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
                    "detail": [
                        {"loc": ["path", "info_item_id"], "msg": "invalid", "type": "value_error"}
                    ]
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
        ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))
        with pytest.raises(NotFound):
            await client.deactivate_rep_spec_assignment(
                "01HZZ00000000000000000000A", "missing"
            )


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
        respx.post(
            f"{BASE_URL}/api/v1/info-items/01HZZ00000000000000000000A/info-sources"
        ).mock(return_value=httpx.Response(201, json=_info_source_out_payload()))
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
async def test_patch_source_revision_cache(client):
    payload = _source_revision_payload()
    payload["content_cache_uri"] = "s3://bucket/key"
    with respx.mock:
        respx.patch(
            f"{BASE_URL}/api/v1/source-revisions/01HZZ00000000000000000000E"
        ).mock(return_value=httpx.Response(200, json=payload))
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
