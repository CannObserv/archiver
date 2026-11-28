"""The authoring tools' fetch leg: one 2xx gate for every tool that reads a target's body.

``AsyncFetchDriver`` captures a non-2xx response into its ``FetchResult`` rather
than raising (co-core-aio): the caller inspects the status. A tool that parses
whatever came back previews or proposes from an error page, and a bot
challenge then reads as "the selector matched nothing" (#473). So
``preview_extraction`` and ``propose_selectors`` fetch through
:func:`fetch_2xx`, which refuses both a transport failure and a non-2xx before
anything reads the body.

``fetch_and_render`` stays outside the 2xx gate: it is the raw inspection tool and
hands ``status_code`` to its caller. It shares the transport leg,
:func:`fetch_target`, so all three tools call an unreachable target
``target_unreachable`` (#561).

The challenge hint is advisory text. Archiver never solves or works around a bot
challenge: the way forward is an allowlist arranged with the site's owner, or
another source.
"""

from collections.abc import Mapping
from http import HTTPStatus

import httpx
from co_core.effects.fetch import FetchContent, FetchResult
from co_core_aio.fetch import AsyncFetchDriver


class TargetUnreachableError(Exception):
    """Raised when the fetch can't reach the target (a transport error)."""


class TargetHttpError(Exception):
    """Raised when the target answered with a non-2xx status: there is no body to read.

    ``challenge`` is true when the response carries ``cf-mitigated: challenge``
    (a Cloudflare bot challenge). ``status_line`` names the status, its reason
    phrase when the status is a registered one, and the challenge:
    ``HTTP 403 Forbidden (Cloudflare bot challenge)``. The message is
    ``target answered <status_line>``.
    """

    def __init__(self, status_code: int, *, challenge: bool) -> None:
        self.status_code = status_code
        self.challenge = challenge
        self.status_line = _status_line(status_code, challenge=challenge)
        super().__init__(f"target answered {self.status_line}")


def _status_line(status_code: int, *, challenge: bool) -> str:
    """``HTTP 403 Forbidden (Cloudflare bot challenge)``; no phrase for an unregistered code."""
    try:
        status = f"{status_code} {HTTPStatus(status_code).phrase}"
    except ValueError:
        status = str(status_code)
    hint = " (Cloudflare bot challenge)" if challenge else ""
    return f"HTTP {status}{hint}"


def _is_challenge(headers: Mapping[str, str]) -> bool:
    """True when ``cf-mitigated: challenge`` is present, whatever the header name's case."""
    return any(
        k.lower() == "cf-mitigated" and v.strip().lower() == "challenge" for k, v in headers.items()
    )


async def fetch_target(driver: AsyncFetchDriver, url: str) -> FetchResult:
    """Fetch ``url`` and return the result, whatever its status.

    Raises:
        TargetUnreachableError: on a transport error (``httpx.HTTPError``): DNS,
            a refused connection, a timeout, or a TLS error that outlasts the
            driver's retries.
    """
    try:
        return await driver.execute(FetchContent(url))
    except httpx.HTTPError as e:
        # A timeout's text is often empty (httpx.ReadTimeout('')): name its class then.
        raise TargetUnreachableError(str(e) or type(e).__name__) from e


async def fetch_2xx(driver: AsyncFetchDriver, url: str) -> FetchResult:
    """Fetch ``url`` and return the result only if it carries a 2xx body.

    Uses ``is_2xx``, not ``is_success``: the latter passes a body-less 3xx such as
    a 304 (co-core #259). The driver follows redirects, so a 200 reached through
    one passes.

    Raises:
        TargetUnreachableError: on a transport error (``httpx.HTTPError``).
        TargetHttpError: on any non-2xx status.
    """
    result = await fetch_target(driver, url)
    if not result.is_2xx:
        raise TargetHttpError(result.status_code, challenge=_is_challenge(result.headers))
    return result
