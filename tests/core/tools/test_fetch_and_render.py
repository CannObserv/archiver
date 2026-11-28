"""Unit tests for src/core/tools/fetch_and_render.py: the raw inspection tool."""

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.core.tools.fetch_and_render import MAX_BODY_BYTES, fetch_and_render
from src.core.tools.target_fetch import TargetUnreachableError


def _driver(status_code: int = 200, content: bytes = b"body", exc=None):
    class _Stub:
        async def execute(self, effect) -> FetchResult:
            if exc is not None:
                raise exc
            return FetchResult(
                content=content,
                status_code=status_code,
                headers={},
                duration_ms=1,
                fetcher_used="http",
            )

    return _Stub()


@pytest.mark.asyncio
async def test_a_non_2xx_is_returned_with_its_status():
    """A non-2xx is not refused: the caller reads ``status_code`` (target_fetch's docstring)."""
    result = await fetch_and_render(_driver(404, b"gone"), "https://example.com")
    assert result.status_code == 404
    assert result.body == "gone"


@pytest.mark.asyncio
async def test_a_transport_error_raises_target_unreachable():
    """#561: it was a bare ``httpx.HTTPError``, which the route answered 500."""
    cause = httpx.ConnectError("[Errno -2] Name or service not known")
    with pytest.raises(TargetUnreachableError, match="Name or service not known") as exc_info:
        await fetch_and_render(_driver(exc=cause), "https://nonexistent.invalid/")
    assert exc_info.value.__cause__ is cause


@pytest.mark.asyncio
async def test_render_true_raises_before_fetching():
    """``render=True`` stays NotImplementedError (the route's 501); the driver is never called."""
    with pytest.raises(NotImplementedError):
        await fetch_and_render(_driver(exc=AssertionError("fetched")), "https://x", render=True)


@pytest.mark.asyncio
async def test_a_body_over_the_cap_is_truncated():
    result = await fetch_and_render(_driver(content=b"a" * (MAX_BODY_BYTES + 1)), "https://x")
    assert result.truncated is True
    assert result.body_bytes_total == MAX_BODY_BYTES + 1
    assert len(result.body) == MAX_BODY_BYTES
