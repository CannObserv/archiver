"""Tests for POST /api/v1/tools/preview-extraction."""

import httpx
import pytest

from src.api.deps import get_http_fetcher
from src.api.main import app
from src.core.fetchers.base import FetchResult

HEADERS = {"X-API-Key": "test-secret-key"}

VALID_FULL_PAGE_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "full_page"},
    "fingerprint": {},
}

VALID_CSS_SPEC = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": ".target"},
    "fingerprint": {},
}

HTML_FIXTURE = (
    b"<html><body><div class='target'>kept content</div><div>dropped content</div></body></html>"
)

DEFAULT_URL = "https://example.com"


def _stub_fetcher(content: bytes = HTML_FIXTURE, *, raise_exc: Exception | None = None):
    class _Stub:
        async def fetch(self, url: str, config: dict | None = None):
            if raise_exc is not None:
                raise raise_exc
            return FetchResult(
                content=content,
                status_code=200,
                headers={"content-type": "text/html"},
                duration_ms=5,
                fetcher_used="http",
            )

    return _Stub()


@pytest.mark.asyncio
async def test_preview_extraction_full_page_returns_chunks_and_simhash(client):
    app.dependency_overrides[get_http_fetcher] = lambda: _stub_fetcher()
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["chunks"]) >= 1
    joined = " ".join(c["text"] for c in body["chunks"])
    assert "kept content" in joined
    assert body["total_chars"] > 0
    assert body["fingerprint_algorithm"] == "sha256"
    assert body["computed_fingerprint"].startswith("sha256:")
    assert "page_title" in body


@pytest.mark.asyncio
async def test_preview_extraction_css_filters_to_selector(client):
    app.dependency_overrides[get_http_fetcher] = lambda: _stub_fetcher()
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": VALID_CSS_SPEC},
    )
    assert response.status_code == 200
    body = response.json()
    joined = " ".join(c["text"] for c in body["chunks"])
    assert "kept content" in joined
    assert "dropped content" not in joined
    assert body["fingerprint_algorithm"] == "sha256"
    assert body["computed_fingerprint"].startswith("sha256:")


@pytest.mark.asyncio
async def test_preview_extraction_invalid_spec_returns_422_with_errors(client):
    bad_spec = {"schema_version": 1, "fingerprint": {}}  # missing extraction
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": bad_spec},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "schema"
    assert detail["message"] == "source_spec validation failed"
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) >= 1


@pytest.mark.asyncio
async def test_preview_extraction_unreachable_target_returns_422_target_unreachable(client):
    app.dependency_overrides[get_http_fetcher] = lambda: _stub_fetcher(
        raise_exc=httpx.ConnectError("nope")
    )
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "target_unreachable"
    assert detail["errors"][0]["path"] == "/url"


@pytest.mark.asyncio
async def test_preview_extraction_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
    )
    assert response.status_code == 403
