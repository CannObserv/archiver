"""Tests for POST /api/v1/tools/fetch-and-render."""

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.api.deps import get_fetch_driver
from src.api.main import app
from tests.api.conftest import TlsReadErrorTransport

HEADERS = {"X-API-Key": "test-secret-key"}


def _override_with_error(exc: Exception) -> None:
    """Inject a stub fetch driver whose fetch raises ``exc`` for any URL."""

    class _FailingFetcher:
        async def execute(self, effect):
            raise exc

    app.dependency_overrides[get_fetch_driver] = lambda: _FailingFetcher()


def _assert_target_unreachable(response, message: str | None = None) -> None:
    """The siblings' refusal (#473): 422 ``kind="domain"``, ``target_unreachable`` at ``/url``."""
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["kind"] == "domain"
    assert len(detail["errors"]) == 1
    error = detail["errors"][0]
    assert error["code"] == "target_unreachable"
    assert error["path"] == "/url"
    assert error["message"]
    if message is not None:
        assert error["message"] == message
        assert detail["message"] == message
    assert detail.get("data") is None


def _override_with_response(response: httpx.Response) -> None:
    """Inject a stub fetch driver that returns ``response`` for any URL."""

    class _StubFetcher:
        async def execute(self, effect):
            return FetchResult(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                duration_ms=12,
                fetcher_used="http",
            )

    app.dependency_overrides[get_fetch_driver] = lambda: _StubFetcher()


@pytest.mark.asyncio
async def test_fetch_and_render_returns_body_and_headers(client):
    _override_with_response(
        httpx.Response(200, content=b"<html>hi</html>", headers={"content-type": "text/html"})
    )
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    # HttpUrl normalises bare-domain URLs with a trailing slash.
    assert body["url"] == "https://example.com/"
    assert body["status_code"] == 200
    assert body["body"] == "<html>hi</html>"
    assert body["body_bytes_total"] == len(b"<html>hi</html>")
    assert body["truncated"] is False
    assert body["screenshot_url"] is None
    assert body["headers"]["content-type"] == "text/html"


@pytest.mark.asyncio
async def test_fetch_and_render_truncates_large_bodies(client):
    big = b"a" * (6 * 1024 * 1024)  # 6 MiB
    _override_with_response(httpx.Response(200, content=big))
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://example.com/big"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["body"].encode()) <= 5 * 1024 * 1024
    assert body["body_bytes_total"] == len(big)


@pytest.mark.asyncio
async def test_fetch_and_render_render_true_returns_501(client):
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://example.com", "render": True},
    )
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert detail["kind"] == "unimplemented"
    assert "Playwright" in detail["message"]


@pytest.mark.asyncio
async def test_fetch_and_render_requires_api_key(client):
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        json={"url": "https://example.com"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_fetch_and_render_passes_url_to_fetcher(client):
    captured = {}

    class _SpyFetcher:
        async def execute(self, effect):
            captured["url"] = effect.url
            return FetchResult(
                content=b"ok", status_code=200, headers={}, duration_ms=1, fetcher_used="http"
            )

    app.dependency_overrides[get_fetch_driver] = lambda: _SpyFetcher()
    await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://target.example.com/path"},
    )
    # The route forwards the (normalised) URL to the fetcher unchanged.
    assert captured["url"] == "https://target.example.com/path"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.ConnectError("[Errno -2] Name or service not known"), None),
        (httpx.ConnectTimeout("timed out"), "timed out"),
        (httpx.ReadTimeout(""), "ReadTimeout"),
        (httpx.ReadError("bad record mac"), "bad record mac"),
    ],
    ids=["dns", "connect-timeout", "empty-read-timeout", "read-error"],
)
async def test_fetch_and_render_transport_error_returns_422_target_unreachable(
    client, exc, message
):
    """#561: a transport error answered 500 ``kind="server"``; the siblings answer 422.

    A timeout's text is empty, so the message names the class and ``/url`` is not blank.
    """
    _override_with_error(exc)
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://nonexistent.invalid/"},
    )
    _assert_target_unreachable(response, message or str(exc))


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 403, 503])
async def test_fetch_and_render_non_2xx_stays_200_with_status_code(client, status_code):
    """#561: transport errors only. A non-2xx is the raw tool's answer, not a refusal."""
    _override_with_response(
        httpx.Response(
            status_code, content=b"<html>nope</html>", headers={"cf-mitigated": "challenge"}
        )
    )
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://example.com/missing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == status_code
    assert body["body"] == "<html>nope</html>"


@pytest.mark.asyncio
async def test_fetch_and_render_render_true_is_501_before_any_fetch(client):
    """#561: ``render=True`` keeps its 501 even when the target is unreachable."""
    _override_with_error(AssertionError("render=True must not fetch"))
    response = await client.post(
        "/api/v1/tools/fetch-and-render",
        headers=HEADERS,
        json={"url": "https://nonexistent.invalid/", "render": True},
    )
    assert response.status_code == 501
    assert response.json()["detail"]["kind"] == "unimplemented"


@pytest.mark.asyncio
async def test_fetch_and_render_persistent_tls_read_error_returns_422_target_unreachable(
    client, tls_read_error_driver
):
    """#561, #445: the raw ``ssl.SSLError`` arrives as ``httpx.ReadError`` after co-core's
    retries. The message is OpenSSL's text, which varies by build, so it isn't pinned."""
    driver = tls_read_error_driver(failures=100)
    try:
        response = await client.post(
            "/api/v1/tools/fetch-and-render",
            headers=HEADERS,
            json={"url": "https://example.com/"},
        )
    finally:
        await driver.aclose()
    # The fake was reached, and retried: not a real fetch.
    assert TlsReadErrorTransport.attempts > 1
    _assert_target_unreachable(response)


@pytest.mark.asyncio
async def test_fetch_and_render_retries_a_one_off_tls_read_error(client, tls_read_error_driver):
    """#445: a GET retries the re-spelled ``ReadError``, so one bad record still renders."""
    driver = tls_read_error_driver(failures=1, body=b"<html>after retry</html>")
    try:
        response = await client.post(
            "/api/v1/tools/fetch-and-render",
            headers=HEADERS,
            json={"url": "https://example.com/"},
        )
    finally:
        await driver.aclose()
    assert TlsReadErrorTransport.attempts == 2
    assert response.status_code == 200
    assert response.json()["body"] == "<html>after retry</html>"
