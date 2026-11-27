"""Tests for POST /api/v1/tools/preview-extraction."""

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.api.deps import get_fetch_driver
from src.api.main import app
from tests.api.conftest import TlsReadErrorTransport

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


def _stub_fetcher(
    content: bytes = HTML_FIXTURE,
    *,
    raise_exc: Exception | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
):
    class _Stub:
        async def execute(self, effect):
            if raise_exc is not None:
                raise raise_exc
            return FetchResult(
                content=content,
                status_code=status_code,
                headers={"content-type": "text/html"} | (headers or {}),
                duration_ms=5,
                fetcher_used="http",
            )

    return _Stub()


@pytest.mark.asyncio
async def test_preview_extraction_full_page_returns_chunks_and_simhash(client):
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher()
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
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher()
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
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher(
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
async def test_preview_extraction_persistent_tls_read_error_returns_422_target_unreachable(
    client, tls_read_error_driver
):
    """#445: co-core-aio 0.39.4 re-spells it ``httpx.ReadError``; before, a raw
    ``ssl.SSLError`` passed ``fetch_2xx``'s ``except httpx.HTTPError`` and answered 500.
    The message is OpenSSL's text, which varies by build, so it isn't pinned."""
    driver = tls_read_error_driver(failures=100, body=HTML_FIXTURE)
    try:
        response = await client.post(
            "/api/v1/tools/preview-extraction",
            headers=HEADERS,
            json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
        )
    finally:
        await driver.aclose()
    # The fake was reached: had co-core stopped building its inner transport as
    # httpx.AsyncHTTPTransport, the patch would be bypassed and this a real fetch.
    assert TlsReadErrorTransport.attempts > 1
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "target_unreachable"
    assert detail["errors"][0]["path"] == "/url"


@pytest.mark.asyncio
async def test_preview_extraction_retries_a_one_off_tls_read_error(client, tls_read_error_driver):
    """#445: a GET retries the re-spelled ``ReadError``, so one bad record previews."""
    driver = tls_read_error_driver(failures=1, body=HTML_FIXTURE)
    try:
        response = await client.post(
            "/api/v1/tools/preview-extraction",
            headers=HEADERS,
            json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
        )
    finally:
        await driver.aclose()
    assert response.status_code == 200
    assert response.json()["chunks"]
    assert TlsReadErrorTransport.attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "headers", "challenge", "message"),
    [
        (
            403,
            {"cf-mitigated": "challenge"},
            True,
            "target answered HTTP 403 Forbidden (Cloudflare bot challenge)",
        ),
        (404, {}, False, "target answered HTTP 404 Not Found"),
        (503, {}, False, "target answered HTTP 503 Service Unavailable"),
    ],
    ids=["403-challenge", "404", "503"],
)
async def test_preview_extraction_non_2xx_returns_422_target_http_error(
    client, status_code, headers, challenge, message
):
    """A captured error page is refused, not previewed (#473)."""
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher(
        status_code=status_code, headers=headers
    )
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": VALID_CSS_SPEC},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["message"] == message
    assert detail["errors"] == [{"path": "/url", "message": message, "code": "target_http_error"}]
    assert detail["data"] == {"status_code": status_code, "challenge": challenge}


@pytest.mark.asyncio
async def test_preview_extraction_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_preview_extraction_xpath_on_html_returns_200(client):
    """co-core 0.38 honours ``xpath`` on HTML (cannobserv#557, #355)."""
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher()
    spec = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//div"},
        "fingerprint": {},
    }
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": spec},
    )
    assert response.status_code == 200
    assert response.json()["chunks"]


@pytest.mark.asyncio
async def test_preview_extraction_extractor_refusal_returns_422_schema(client):
    """co-core refuses an invalid xpath rather than previewing the whole page (#317)."""
    app.dependency_overrides[get_fetch_driver] = lambda: _stub_fetcher()
    spec = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//div["},
        "fingerprint": {},
    }
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": spec},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "schema"
    assert [e["path"] for e in detail["errors"]] == ["/extraction"]


@pytest.mark.asyncio
async def test_preview_extraction_unparseable_body_returns_422_extraction_failed(client):
    """The dispatched extractor's parse failure is the target's fault, not a 500 (#317)."""

    class _XmlStub:
        async def execute(self, effect):
            return FetchResult(
                content=b"<rss><unclosed>",
                status_code=200,
                headers={"content-type": "application/rss+xml"},
                duration_ms=5,
                fetcher_used="http",
            )

    app.dependency_overrides[get_fetch_driver] = lambda: _XmlStub()
    response = await client.post(
        "/api/v1/tools/preview-extraction",
        headers=HEADERS,
        json={"url": DEFAULT_URL, "source_spec": VALID_FULL_PAGE_SPEC},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert [(e["path"], e["code"]) for e in detail["errors"]] == [("/url", "extraction_failed")]
