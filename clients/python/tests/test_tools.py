"""Tests for the authoring-tool wrappers in archiver_client.tools (v2)."""

import httpx
import pytest
import respx

from archiver_client import FieldError
from archiver_client.generated.types import UNSET

BASE_URL = "http://archiver.test"

_TS = "2026-05-04T00:00:00Z"

VALID_SOURCE_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}

VALID_SOURCE_URL = "https://example.com"

VALID_REP_SPEC = {
    "schema_version": 1,
    "format": "pdf",
    "provider": "s3",
}


def _info_item_payload(info_item_id: str, name: str) -> dict:
    return {
        "info_item_id": info_item_id,
        "name": name,
        "description": None,
        "owner": None,
        "rep_fields": {},
        "created_at": _TS,
        "updated_at": _TS,
    }


# --- validate_source_spec ---


@pytest.mark.asyncio
async def test_validate_source_spec_valid(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/validate-source-spec").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        result = await client.validate_source_spec(VALID_SOURCE_SPEC)
    assert route.called
    assert result.valid is True
    assert result.errors == []


@pytest.mark.asyncio
async def test_validate_source_spec_invalid_returns_structured_errors(client):
    """Server emits ``path`` as a JSON-Pointer string; SDK must surface it verbatim."""
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/validate-source-spec").mock(
            return_value=httpx.Response(
                200,
                json={
                    "valid": False,
                    "errors": [{"path": "/target", "message": "'target' is required"}],
                },
            )
        )
        result = await client.validate_source_spec({})
    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == "/target"
    assert isinstance(result.errors[0].path, str)
    assert isinstance(result.errors[0], FieldError)


@pytest.mark.asyncio
async def test_validate_source_spec_preserves_code(client):
    """Server's ``FieldError.code`` is optional but, when set, must round-trip to the SDK."""
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/validate-source-spec").mock(
            return_value=httpx.Response(
                200,
                json={
                    "valid": False,
                    "errors": [
                        {
                            "path": "/target",
                            "message": "'target' is required",
                            "code": "required",
                        }
                    ],
                },
            )
        )
        result = await client.validate_source_spec({})
    assert result.errors[0].code == "required"


@pytest.mark.asyncio
async def test_validate_source_spec_handles_missing_code(client):
    """``code`` is optional; absence must not crash the parser."""
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/validate-source-spec").mock(
            return_value=httpx.Response(
                200,
                json={
                    "valid": False,
                    "errors": [{"path": "/target", "message": "'target' is required"}],
                },
            )
        )
        result = await client.validate_source_spec({})
    fe = result.errors[0]
    assert fe.path == "/target"
    assert fe.message == "'target' is required"
    # Generated dataclass uses UNSET sentinel for absent optionals — pin to that
    # rather than `is None`; the field type is ``None | str | Unset``.
    assert fe.code is UNSET


@pytest.mark.asyncio
async def test_validate_source_spec_sends_document_in_body(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/validate-source-spec").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        await client.validate_source_spec(VALID_SOURCE_SPEC)
    sent_body = route.calls[0].request.read()
    assert b'"document"' in sent_body
    assert b'"schema_version"' in sent_body


# --- validate_rep_spec ---


@pytest.mark.asyncio
async def test_validate_rep_spec_valid(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/validate-rep-spec").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        result = await client.validate_rep_spec(VALID_REP_SPEC)
    assert route.called
    assert result.valid is True


@pytest.mark.asyncio
async def test_validate_rep_spec_invalid(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/validate-rep-spec").mock(
            return_value=httpx.Response(
                200,
                json={
                    "valid": False,
                    "errors": [{"path": "/format", "message": "'format' is required"}],
                },
            )
        )
        result = await client.validate_rep_spec({})
    assert result.valid is False
    assert result.errors[0].message == "'format' is required"
    assert result.errors[0].path == "/format"
    assert isinstance(result.errors[0].path, str)


# --- validate_rep_fields ---


@pytest.mark.asyncio
async def test_validate_rep_fields_valid(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/validate-rep-fields").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        result = await client.validate_rep_fields({"cannabis": {"license_type": "cultivator"}})
    assert result.valid is True


@pytest.mark.asyncio
async def test_validate_rep_fields_with_required_fields(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/validate-rep-fields").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        await client.validate_rep_fields(
            {"cannabis": {"license_type": "cultivator"}},
            required_fields=["cannabis.license_type"],
        )
    sent_body = route.calls[0].request.read()
    assert b'"required_fields"' in sent_body
    assert b'"cannabis.license_type"' in sent_body


@pytest.mark.asyncio
async def test_validate_rep_fields_sends_bag(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/validate-rep-fields").mock(
            return_value=httpx.Response(200, json={"valid": True, "errors": []})
        )
        await client.validate_rep_fields({"cannabis": {"license_type": "cultivator"}})
    sent_body = route.calls[0].request.read()
    assert b'"bag"' in sent_body


# --- resolve_rep_fields ---


@pytest.mark.asyncio
async def test_resolve_rep_fields_returns_enriched_bag(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/resolve-rep-fields").mock(
            return_value=httpx.Response(
                200,
                json={
                    "bag": {
                        "cannabis": {
                            "license_type": "cultivator",
                            "license_type_slug": "cultivator",
                        }
                    }
                },
            )
        )
        result = await client.resolve_rep_fields({"cannabis": {"license_type": "cultivator"}})
    assert result["cannabis"]["license_type_slug"] == "cultivator"


@pytest.mark.asyncio
async def test_resolve_rep_fields_sends_bag(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/resolve-rep-fields").mock(
            return_value=httpx.Response(200, json={"bag": {}})
        )
        await client.resolve_rep_fields({"cannabis": {}})
    sent_body = route.calls[0].request.read()
    assert b'"bag"' in sent_body


# --- find_info_item ---


@pytest.mark.asyncio
async def test_find_info_item_returns_typed_list(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/tools/find-info-items").mock(
            return_value=httpx.Response(
                200,
                json=[
                    _info_item_payload("01HZZ00000000000000000000A", "Colorado licenses"),
                    _info_item_payload("01HZZ00000000000000000000B", "Colorado regulator"),
                ],
            )
        )
        results = await client.find_info_item("colorado")
    assert len(results) == 2
    assert results[0].name == "Colorado licenses"
    assert results[1].name == "Colorado regulator"


@pytest.mark.asyncio
async def test_find_info_item_passes_query_and_limit(client):
    with respx.mock:
        route = respx.get(f"{BASE_URL}/api/v1/tools/find-info-items").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.find_info_item("alpha", limit=5)
    sent_url = str(route.calls[0].request.url)
    assert "q=alpha" in sent_url
    assert "limit=5" in sent_url


@pytest.mark.asyncio
async def test_find_info_item_empty_result(client):
    with respx.mock:
        respx.get(f"{BASE_URL}/api/v1/tools/find-info-items").mock(
            return_value=httpx.Response(200, json=[])
        )
        results = await client.find_info_item("nothing")
    assert results == []


# --- create_info_item with initial_url + initial_source_specs ---


@pytest.mark.asyncio
async def test_create_info_item_with_source_sends_initial_url_and_specs(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/info-items").mock(
            return_value=httpx.Response(
                201,
                json=_info_item_payload("01HZZ00000000000000000000A", "X"),
            )
        )
        await client.create_info_item(
            name="X",
            initial_url=VALID_SOURCE_URL,
            initial_source_specs=[VALID_SOURCE_SPEC],
        )
    sent_body = route.calls[0].request.read()
    assert b'"initial_url"' in sent_body
    assert b'"initial_source_specs"' in sent_body


@pytest.mark.asyncio
async def test_create_info_item_without_source_spec(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/info-items").mock(
            return_value=httpx.Response(
                201,
                json=_info_item_payload("01HZZ00000000000000000000A", "X"),
            )
        )
        result = await client.create_info_item(name="X")
    assert result.name == "X"


# --- fetch_and_render ---


@pytest.mark.asyncio
async def test_fetch_and_render_returns_typed_result(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/fetch-and-render").mock(
            return_value=httpx.Response(
                200,
                json={
                    "url": "https://example.com/",
                    "status_code": 200,
                    "headers": {"content-type": "text/html"},
                    "body": "<html>hi</html>",
                    "body_bytes_total": 16,
                    "truncated": False,
                    "screenshot_url": None,
                },
            )
        )
        result = await client.fetch_and_render("https://example.com")
    assert result.status_code == 200
    assert result.body == "<html>hi</html>"
    assert result.truncated is False
    assert result.headers["content-type"] == "text/html"


# --- preview_extraction (v2: source_spec key) ---


@pytest.mark.asyncio
async def test_preview_extraction_returns_typed_result(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/preview-extraction").mock(
            return_value=httpx.Response(
                200,
                json={
                    "chunks": [
                        {
                            "index": 0,
                            "chunk_type": "page",
                            "label": "page-1",
                            "text": "kept",
                            "char_count": 4,
                        }
                    ],
                    "total_chars": 4,
                    "fingerprint_algorithm": "simhash",
                    "computed_fingerprint": "12345",
                },
            )
        )
        result = await client.preview_extraction(VALID_SOURCE_URL, VALID_SOURCE_SPEC)
    assert len(result.chunks) == 1
    assert result.chunks[0].text == "kept"
    assert result.total_chars == 4
    assert result.fingerprint_algorithm == "simhash"
    assert result.computed_fingerprint == "12345"


@pytest.mark.asyncio
async def test_preview_extraction_sends_source_spec_key(client):
    """v2: body key is ``source_spec``, not ``document``."""
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/preview-extraction").mock(
            return_value=httpx.Response(
                200,
                json={
                    "chunks": [],
                    "total_chars": 0,
                    "fingerprint_algorithm": "simhash",
                    "computed_fingerprint": "0",
                },
            )
        )
        await client.preview_extraction(VALID_SOURCE_URL, VALID_SOURCE_SPEC)
    sent_body = route.calls[0].request.read()
    assert b'"url"' in sent_body
    assert b'"source_spec"' in sent_body
    assert b'"document"' not in sent_body


# --- propose_selectors ---


@pytest.mark.asyncio
async def test_propose_selectors_returns_typed_candidates(client):
    with respx.mock:
        respx.post(f"{BASE_URL}/api/v1/tools/propose-selectors").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "selector": "h1.page-title",
                        "sample_text": "Active Cannabis Licenses",
                        "stability_score": 0.85,
                    },
                ],
            )
        )
        results = await client.propose_selectors("https://example.com", "Active Cannabis Licenses")
    assert len(results) == 1
    assert results[0].selector == "h1.page-title"
    assert results[0].stability_score == 0.85


@pytest.mark.asyncio
async def test_propose_selectors_passes_top_k(client):
    with respx.mock:
        route = respx.post(f"{BASE_URL}/api/v1/tools/propose-selectors").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.propose_selectors("https://example.com", "x", top_k=3)
    sent_body = route.calls[0].request.read()
    assert b'"top_k": 3' in sent_body or b'"top_k":3' in sent_body
