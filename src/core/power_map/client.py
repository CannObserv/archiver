"""The Power Map adapter: the one module that imports the Power Map SDK (archiver#304).

Power Map (CannObserv/power-map) is the cluster's identity system of record, and
``org.*`` rep_fields come from its orgs. The SDK (``power-map-client``) is
generated and deliberately thin: a ``Response`` per documented status, attrs
models, no retries and no error taxonomy. This module supplies those, so nothing
outside ``src/core/power_map/`` sees a generated type:

- ``get_org`` maps to ``Snapshot | NotModified | Merged | Gone``: 410 with
  ``merged_into`` is ``Merged`` (power-map#607), 410 without it or 404 is
  ``Gone``.
- Everything that is not an answer about the org - a timeout, a refused
  connection, 429, 5xx, a rejected key, a body that is not an org - raises
  ``PowerMapUnavailableError``. The caller decides what that costs (the link
  route answers 503); the adapter never retries in-request, because the
  authoring path is a person waiting.

**Edge rule.** Power Map is called on the authoring path and by the follower,
never during replication: rendering reads only the local ``pm_organizations``
snapshot. See CLAUDE.md.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import power_map_client
from power_map_client.generated.api.public_api import get_org, search_orgs
from power_map_client.generated.models.entity_gone import EntityGone
from power_map_client.generated.models.org_detail import OrgDetail
from power_map_client.generated.models.org_search_response import OrgSearchResponse
from power_map_client.generated.types import UNSET, Unset

from src.core.logging import get_logger

logger = get_logger(__name__)

API_KEY_ENV = "ARCHIVER_POWER_MAP_API_KEY"
BASE_URL_ENV = "ARCHIVER_POWER_MAP_BASE_URL"
DEFAULT_BASE_URL = "https://power-map.exe.xyz"
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class OrgSnapshot:
    """One Power Map org as archiver keeps it: the fields ``pm_organizations`` mirrors."""

    pm_org_id: str
    name: str | None
    acronym: str | None
    archived_at: datetime | None
    active: bool
    succeeded_by: str | None
    pm_updated_at: datetime
    etag: str | None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """200: the org as it is now."""

    org: OrgSnapshot


@dataclass(frozen=True, slots=True)
class NotModified:
    """304: the ETag sent still matches."""


@dataclass(frozen=True, slots=True)
class Merged:
    """410 with ``merged_into``: the id was merged away; ``winner`` is the chain's live end."""

    winner: str


@dataclass(frozen=True, slots=True)
class Gone:
    """404, or 410 with no ``merged_into``: Power Map has no such org."""


OrgResult = Snapshot | NotModified | Merged | Gone


@dataclass(frozen=True, slots=True)
class OrgHit:
    """One search result: enough to label a choice, not a snapshot."""

    pm_org_id: str
    name: str | None
    acronym: str | None
    archived_at: datetime | None
    succeeded_by: str | None


class PowerMapUnavailableError(Exception):
    """Power Map gave no answer about the org: transport failure, 429, 5xx, rejected key.

    ``retry_after`` is the 429's ``Retry-After`` in seconds, when it sent one.
    """

    def __init__(self, reason: str, *, retry_after: float | None = None) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(f"Power Map unavailable: {reason}")


class PowerMapClient:
    """Archiver's Power Map client: ``get_org`` and ``search_orgs`` over the SDK.

    ``transport`` is for tests (an ``httpx.MockTransport``). One instance owns
    one connection pool; ``aclose`` releases it.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        httpx_args: dict[str, Any] = {}
        if transport is not None:
            httpx_args["transport"] = transport
        self._client = power_map_client.connect(
            self.base_url,
            api_key,
            timeout=httpx.Timeout(timeout),
            httpx_args=httpx_args,
        )

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self._client.get_async_httpx_client().aclose()

    async def get_org(self, pm_org_id: str, etag: str | None = None) -> OrgResult:
        """Fetch one org, conditionally when ``etag`` is given.

        Raises:
            PowerMapUnavailableError: no answer about the org.
        """
        try:
            response = await get_org.asyncio_detailed(
                pm_org_id,
                client=self._client,
                if_none_match=etag if etag is not None else UNSET,
            )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise _transport_unavailable(e) from e

        status = int(response.status_code)
        parsed = response.parsed
        if status == 200 and isinstance(parsed, OrgDetail):
            return Snapshot(org=_snapshot(parsed, response.headers.get("etag")))
        if status == 304:
            return NotModified()
        if status == 410 and isinstance(parsed, EntityGone):
            return Merged(winner=parsed.merged_into) if parsed.merged_into else Gone()
        if status == 404:
            return Gone()
        raise _status_unavailable(status, response.headers)

    async def search_orgs(self, q: str, limit: int = 10) -> list[OrgHit]:
        """Full-text org search, archived orgs excluded.

        Raises:
            PowerMapUnavailableError: no answer.
        """
        try:
            response = await search_orgs.asyncio_detailed(
                client=self._client, q=q, limit=limit, include_archived=False
            )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise _transport_unavailable(e) from e

        status = int(response.status_code)
        parsed = response.parsed
        if status == 200 and isinstance(parsed, OrgSearchResponse):
            return [
                OrgHit(
                    pm_org_id=hit.id,
                    name=_opt(hit.name),
                    acronym=_opt(hit.acronym),
                    archived_at=_opt(hit.archived_at),
                    succeeded_by=_opt(hit.succeeded_by),
                )
                for hit in parsed.data
            ]
        raise _status_unavailable(status, response.headers)


def power_map_from_env() -> PowerMapClient | None:
    """A client when ``ARCHIVER_POWER_MAP_API_KEY`` is set, else ``None`` (dormant).

    The key is the switch: Power Map has one production deployment, so the base
    URL defaults to it. ``scripts/dev_server.sh`` never passes production's key
    through - a dev server reads ``ARCHIVER_DEV_POWER_MAP_API_KEY`` or stays
    dormant, the ``ARCHIVER_DEV_REDIS_URL`` rule. Read straight from
    ``os.environ`` so ``tests/outbound_env_audit.py`` sees both names.
    """
    api_key = (os.environ.get(API_KEY_ENV) or "").strip()
    if not api_key:
        return None
    base_url = (os.environ.get(BASE_URL_ENV) or "").strip() or DEFAULT_BASE_URL
    return PowerMapClient(base_url, api_key)


def _opt[T](value: T | None | Unset) -> T | None:
    return None if isinstance(value, Unset) else value


def _snapshot(detail: OrgDetail, etag: str | None) -> OrgSnapshot:
    return OrgSnapshot(
        pm_org_id=detail.id,
        name=_opt(detail.name),
        acronym=_opt(detail.acronym),
        archived_at=_opt(detail.archived_at),
        active=detail.active,
        succeeded_by=_opt(detail.succeeded_by),
        pm_updated_at=detail.updated_at,
        etag=etag,
    )


def _transport_unavailable(e: Exception) -> PowerMapUnavailableError:
    if isinstance(e, httpx.TimeoutException):
        reason = "request timed out"
    elif isinstance(e, httpx.HTTPError):
        reason = f"transport error ({type(e).__name__})"
    else:
        reason = f"unreadable response ({type(e).__name__})"
    logger.warning("Power Map unavailable", extra={"reason": reason})
    return PowerMapUnavailableError(reason)


def _status_unavailable(status: int, headers: Mapping[str, str]) -> PowerMapUnavailableError:
    if status in (401, 403):
        reason = f"Power Map rejected archiver's API key (HTTP {status})"
        logger.error("Power Map unavailable", extra={"reason": reason})
        return PowerMapUnavailableError(reason)
    retry_after = _retry_after(headers.get("retry-after")) if status == 429 else None
    reason = "rate limited (HTTP 429)" if status == 429 else f"unexpected HTTP {status}"
    logger.warning("Power Map unavailable", extra={"reason": reason, "retry_after": retry_after})
    return PowerMapUnavailableError(reason, retry_after=retry_after)


def _retry_after(value: str | None) -> float | None:
    """``Retry-After`` as seconds; the HTTP-date form is not one Power Map sends."""
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
