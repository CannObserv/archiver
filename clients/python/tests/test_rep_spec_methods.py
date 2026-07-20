"""respx-mocked tests for ArchiverClient.{create,get,list,update}_rep_spec wrappers."""

import json

import httpx
import pytest
import respx
from archiver_client.errors import Conflict, NotFound, ValidationError

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
    # updated_at is required-but-nullable in the contract: the server always
    # emits it, null meaning "never edited".
    return {
        "rep_spec_id": rep_spec_id,
        "provider": "gcs",
        "name": "x",
        "schema_version": 1,
        "document": _gcs_doc(),
        "created_at": _TS,
        "updated_at": None,
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
        route = respx.get(f"{BASE_URL}/api/v1/rep-specs").mock(
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

    sent = route.calls.last.request.url
    assert sent.params.get("provider") == "gcs"
    assert sent.params.get("limit") == "10"
    assert sent.params.get("offset") == "0"


# ---------------------------------------------------------------------------
# update_rep_spec (archiver#83)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_rep_spec_sends_name_only(client):
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        route = respx.patch(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(200, json=_rep_spec_payload(rid) | {"name": "renamed"})
        )
        out = await client.update_rep_spec(rid, name="renamed")

    body = json.loads(route.calls[0].request.content)
    assert body == {"name": "renamed"}  # document omitted, not sent as null
    assert out.name == "renamed"


@pytest.mark.asyncio
async def test_update_rep_spec_sends_document(client):
    rid = "01HZZ00000000000000000000R"
    new_doc = _gcs_doc() | {"path_template": "corrected/{info_item.slug}.html"}
    with respx.mock:
        route = respx.patch(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(200, json=_rep_spec_payload(rid) | {"document": new_doc})
        )
        out = await client.update_rep_spec(rid, document=new_doc)

    body = json.loads(route.calls[0].request.content)
    assert body["document"]["path_template"] == "corrected/{info_item.slug}.html"
    assert "name" not in body
    assert out.document.to_dict()["path_template"] == "corrected/{info_item.slug}.html"


@pytest.mark.asyncio
async def test_update_rep_spec_conflict_on_assigned_spec(client):
    """409 carries the assignment count that blocked the edit."""
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        respx.patch(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(
                409,
                json={
                    "detail": {
                        "kind": "conflict",
                        "message": "RepSpec document is frozen once assigned",
                        "data": {"rep_spec_id": rid, "assignment_count": 3},
                    }
                },
            )
        )
        with pytest.raises(Conflict) as exc:
            await client.update_rep_spec(rid, document=_gcs_doc())

    assert exc.value.data["assignment_count"] == 3


@pytest.mark.asyncio
async def test_update_rep_spec_validation_error_on_provider_change(client):
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        respx.patch(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(
                422,
                json={
                    "detail": {
                        "kind": "schema",
                        "message": "invalid rep_spec",
                        "errors": [{"path": "/provider", "message": "provider is immutable"}],
                    }
                },
            )
        )
        with pytest.raises(ValidationError):
            await client.update_rep_spec(rid, document=_gcs_doc() | {"provider": "gdrive"})


@pytest.mark.asyncio
async def test_update_rep_spec_not_found(client):
    rid = "01HZZ00000000000000000000R"
    with respx.mock:
        respx.patch(f"{BASE_URL}/api/v1/rep-specs/{rid}").mock(
            return_value=httpx.Response(
                404, json={"detail": {"kind": "lookup", "message": "RepSpec not found"}}
            )
        )
        with pytest.raises(NotFound):
            await client.update_rep_spec(rid, name="x")
