"""Unit tests for src/core/tools/propose_selectors.py: the fetch leg's refusals (#473)."""

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.core.tools import propose_selectors as propose_module
from src.core.tools.propose_selectors import propose_selectors
from src.core.tools.target_fetch import TargetHttpError, TargetUnreachableError

HTML = b"<html><body><h1 class='page-title'>Active Licenses</h1></body></html>"


def _stub_fetcher(
    content: bytes = HTML,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    raise_exc: Exception | None = None,
):
    class _Stub:
        async def execute(self, effect) -> FetchResult:
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


@pytest.fixture
def parse_calls(monkeypatch) -> list[bytes]:
    """Spy on the parse: a refused fetch must never be read for selectors."""
    calls: list[bytes] = []
    original = propose_module.BeautifulSoup

    def _spy(markup, *args, **kwargs):
        calls.append(markup)
        return original(markup, *args, **kwargs)

    monkeypatch.setattr(propose_module, "BeautifulSoup", _spy)
    return calls


@pytest.mark.asyncio
async def test_a_2xx_page_yields_candidates(parse_calls):
    candidates = await propose_selectors(_stub_fetcher(), "https://example.com", "Active Licenses")
    assert candidates[0].selector == "h1.page-title"
    assert parse_calls == [HTML]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc", [httpx.ConnectError("nope"), httpx.TimeoutException("slow")], ids=["connect", "timeout"]
)
async def test_a_transport_error_raises_target_unreachable(exc, parse_calls):
    with pytest.raises(TargetUnreachableError):
        await propose_selectors(_stub_fetcher(raise_exc=exc), "https://example.com", "x")
    assert parse_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "headers", "challenge"),
    [
        (403, {"cf-mitigated": "challenge"}, True),
        (403, {}, False),
        (404, {}, False),
        (503, {}, False),
        (304, {}, False),
    ],
    ids=["403-challenge", "403", "404", "503", "304"],
)
async def test_a_non_2xx_raises_target_http_error_and_is_never_parsed(
    status_code, headers, challenge, parse_calls
):
    with pytest.raises(TargetHttpError) as exc_info:
        await propose_selectors(
            _stub_fetcher(b"<p>Just a moment...</p>", status_code=status_code, headers=headers),
            "https://example.com",
            "Just a moment",
        )
    assert exc_info.value.status_code == status_code
    assert exc_info.value.challenge is challenge
    assert parse_calls == []


@pytest.mark.asyncio
async def test_an_empty_description_never_fetches():
    """Unchanged: no description, no fetch, no refusal."""
    assert await propose_selectors(_stub_fetcher(raise_exc=AssertionError()), "u", "") == []
