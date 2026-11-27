"""Fixtures shared by the API route tests: the tools' raw-TLS-error fetch fake (#445, #561)."""

import ssl

import co_core_aio.transport
import httpx
import pytest
from co_core_aio.fetch import AsyncFetchDriver

from src.api.deps import get_fetch_driver
from src.api.main import app


class TlsReadErrorTransport(httpx.AsyncBaseTransport):
    """Stands in for the library's inner ``httpx.AsyncHTTPTransport``.

    Raises the raw ``ssl.SSLError`` anyio lets through on a non-EOF TLS error
    while reading the answer (cannobserv#597) for the first ``failures`` attempts,
    then answers 200 with ``body`` as ``text/html``.
    """

    failures = 0
    attempts = 0
    body = b"<html><body>ok</body></html>"

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        type(self).attempts += 1
        if type(self).attempts <= type(self).failures:
            raise ssl.SSLError(1, "[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] bad record mac")
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=type(self).body, request=request
        )


@pytest.fixture
def tls_read_error_driver(monkeypatch):
    """The app's own ``AsyncFetchDriver()`` (no client argument, so the library's
    resilient transport), over :class:`TlsReadErrorTransport`, with no backoff.

    Call it with ``failures`` (and optionally the 200's ``body``); close the
    returned driver with ``aclose()``.
    """
    monkeypatch.setattr(TlsReadErrorTransport, "attempts", 0)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", TlsReadErrorTransport)
    monkeypatch.setattr(co_core_aio.transport, "backoff_delay", lambda *a, **k: 0.0)

    def _build(failures: int, body: bytes | None = None) -> AsyncFetchDriver:
        monkeypatch.setattr(TlsReadErrorTransport, "failures", failures)
        if body is not None:
            monkeypatch.setattr(TlsReadErrorTransport, "body", body)
        driver = AsyncFetchDriver()
        app.dependency_overrides[get_fetch_driver] = lambda: driver
        return driver

    return _build
