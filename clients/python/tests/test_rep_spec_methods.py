"""respx-mocked tests for ArchiverClient.{create,get,list}_rep_spec wrappers."""

import httpx
import pytest
import respx

BASE_URL = "http://archiver.test"
_TS = "2026-05-11T00:00:00Z"


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


def _rep_spec_payload(rep_spec_id: str = "01HZZ00000000000000000000R") -> dict:
    return {
        "rep_spec_id": rep_spec_id,
        "provider": "gcs",
        "name": "x",
        "schema_version": 1,
        "document": _gcs_doc(),
        "created_at": _TS,
    }


@pytest.mark.asyncio
async def test_create_rep_spec(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/rep-specs").mock(
            return_value=httpx.Response(201, json=_rep_spec_payload())
        )
        out = await client.create_rep_spec(provider="gcs", name="x", document=_gcs_doc())
    assert out.provider == "gcs"
    assert out.schema_version == 1


@pytest.mark.asyncio
async def test_get_rep_spec(client):
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(200, json=_rep_spec_payload(rid))
        )
        out = await client.get_rep_spec(rid)
    assert str(out.rep_spec_id) == rid


@pytest.mark.asyncio
async def test_list_rep_specs_with_provider_filter(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/rep-specs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [_rep_spec_payload()],
                    "has_more": False,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        page = await client.list_rep_specs(provider="gcs", limit=10, offset=0)
    assert page.has_more is False
    assert page.limit == 10
    assert len(page.items) == 1
