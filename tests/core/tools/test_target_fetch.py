"""Unit tests for src/core/tools/target_fetch.py: the authoring tools' 2xx gate (#473)."""

import httpx
import pytest
from co_core.effects.fetch import FetchResult

from src.core.tools.target_fetch import TargetHttpError, TargetUnreachableError, fetch_2xx


def _driver(status_code: int = 200, headers: dict[str, str] | None = None, exc=None):
    class _Stub:
        async def execute(self, effect) -> FetchResult:
            if exc is not None:
                raise exc
            return FetchResult(
                content=b"body",
                status_code=status_code,
                headers=headers or {},
                duration_ms=1,
                fetcher_used="http",
            )

    return _Stub()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 201, 204, 299])
async def test_any_2xx_passes(status_code):
    result = await fetch_2xx(_driver(status_code), "https://example.com")
    assert result.status_code == status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [199, 300, 301, 304, 400, 403, 429, 500, 503])
async def test_anything_else_is_refused(status_code):
    with pytest.raises(TargetHttpError) as exc_info:
        await fetch_2xx(_driver(status_code), "https://example.com")
    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
async def test_a_transport_error_is_unreachable_and_chained():
    cause = httpx.ConnectError("refused")
    with pytest.raises(TargetUnreachableError, match="refused") as exc_info:
        await fetch_2xx(_driver(exc=cause), "https://example.com")
    assert exc_info.value.__cause__ is cause


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "challenge"),
    [
        ({"cf-mitigated": "challenge"}, True),
        ({"CF-MITIGATED": " Challenge "}, True),
        ({"cf-mitigated": "block"}, False),
        ({"server": "cloudflare"}, False),
        ({}, False),
    ],
    ids=["exact", "case-and-space", "other-value", "cloudflare-without-challenge", "none"],
)
async def test_the_challenge_hint_reads_only_cf_mitigated_challenge(headers, challenge):
    with pytest.raises(TargetHttpError) as exc_info:
        await fetch_2xx(_driver(403, headers), "https://example.com")
    assert exc_info.value.challenge is challenge


@pytest.mark.parametrize(
    ("status_code", "challenge", "status_line"),
    [
        (403, True, "HTTP 403 Forbidden (Cloudflare bot challenge)"),
        (503, False, "HTTP 503 Service Unavailable"),
        (599, False, "HTTP 599"),
    ],
)
def test_status_line_and_message(status_code, challenge, status_line):
    err = TargetHttpError(status_code, challenge=challenge)
    assert err.status_line == status_line
    assert str(err) == f"target answered {status_line}"
