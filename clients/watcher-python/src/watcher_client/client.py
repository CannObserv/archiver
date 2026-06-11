"""``WatcherClient`` — Archiver adapter layer.

Wraps a single httpx.AsyncClient with X-API-Key auth and exposes the six
methods the Archiver control plane needs to provision and query WatchedItems.

The generated package under ``watcher_client.generated`` is never imported
here — this adapter works against the live Watcher API directly via httpx.
That keeps the interface stable even if the generated layer needs a regen.

Async-only. No sync facade.
"""

from __future__ import annotations

from types import TracebackType

import httpx

from watcher_client.errors import WatcherServerError, error_from_response
from watcher_client.generated.models.change_revision_response import ChangeRevisionResponse
from watcher_client.generated.models.watched_item_response import WatchedItemResponse


class WatcherClient:
    """Async client for the Watcher service (Archiver adapter layer)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._mask = (api_key[:3] + "***") if api_key else "***"
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(timeout),
        )

    @property
    def base_url(self) -> str:
        """Public base URL of the Watcher service (no trailing slash)."""
        return self._base_url

    def __repr__(self) -> str:
        return f"WatcherClient(base_url={self._base_url!r}, api_key={self._mask!r})"

    async def __aenter__(self) -> WatcherClient:
        await self._http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.__aexit__(exc_type, exc, tb)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # --- Provisioning ---

    async def provision_watched_item(
        self,
        *,
        url: str,
        source_specs: list[dict],
        info_item_id: str,
        archiver_info_source_id: str,
    ) -> WatchedItemResponse:
        """Create a WatchedItem in Watcher for an Archiver InfoItem.

        ``info_item_id`` links the WatchedItem back to the Archiver InfoItem.
        ``archiver_info_source_id`` identifies the active InfoSource so the
        Watcher drain worker can post SourceRevisions to the correct source.
        """
        body = {
            "archiver_info_item_id": info_item_id,
            "url": url,
            "source_specs": source_specs,
            "archiver_info_source_id": archiver_info_source_id,
        }
        resp = await self._http.post("/api/v1/watched-items", json=body)
        return _unwrap_watched_item(resp)

    async def patch_watched_item(
        self,
        watcher_item_id: str,
        *,
        effective_url: str | None = None,
        source_specs: list[dict] | None = None,
        archiver_info_source_id: str | None = None,
    ) -> WatchedItemResponse:
        """Update mutable fields on an existing WatchedItem.

        Only fields explicitly passed (non-None) are included in the PATCH body.
        Used by Archiver on primary-source swap and spec update.
        """
        body: dict = {}
        if effective_url is not None:
            body["effective_url"] = effective_url
        if source_specs is not None:
            body["source_specs"] = source_specs
        if archiver_info_source_id is not None:
            body["archiver_info_source_id"] = archiver_info_source_id
        resp = await self._http.patch(f"/api/v1/watched-items/{watcher_item_id}", json=body)
        return _unwrap_watched_item(resp)

    # --- Queries ---

    async def get_watched_item(self, watcher_item_id: str) -> WatchedItemResponse:
        """Fetch a single WatchedItem by its Watcher-native ID."""
        resp = await self._http.get(f"/api/v1/watched-items/{watcher_item_id}")
        return _unwrap_watched_item(resp)

    async def get_by_info_item_id(self, info_item_id: str) -> WatchedItemResponse | None:
        """Fetch the WatchedItem linked to an Archiver InfoItem ID.

        Returns ``None`` when no WatchedItem has been provisioned for the
        InfoItem yet (pre-integration items, or provisioning failure).
        """
        resp = await self._http.get(
            "/api/v1/watched-items",
            params={"archiver_info_item_id": info_item_id},
        )
        if resp.is_error:
            raise error_from_response(resp.status_code, resp.content)
        items = resp.json()
        if not isinstance(items, list):
            raise WatcherServerError(
                f"expected list from /api/v1/watched-items, got {type(items).__name__}",
                status_code=resp.status_code,
            )
        if not items:
            return None
        return WatchedItemResponse.from_dict(items[0])

    async def check_now(self, watcher_item_id: str) -> WatchedItemResponse:
        """Enqueue an immediate fetch cycle for a WatchedItem.

        Returns the WatchedItem as of the moment of enqueue (health fields
        update asynchronously as the task runs). Raises ``WatcherConflict``
        if the item is archived, ``WatcherValidationError`` if ``effective_url``
        is empty.
        """
        resp = await self._http.post(f"/api/v1/watched-items/{watcher_item_id}/check-now")
        return _unwrap_watched_item(resp)

    async def list_revisions(self, watcher_item_id: str) -> list[ChangeRevisionResponse]:
        """List ChangeRevisions for a WatchedItem, newest first."""
        resp = await self._http.get(f"/api/v1/watched-items/{watcher_item_id}/revisions")
        if resp.is_error:
            raise error_from_response(resp.status_code, resp.content)
        return [ChangeRevisionResponse.from_dict(r) for r in resp.json()]


def _unwrap_watched_item(resp: httpx.Response) -> WatchedItemResponse:
    """Parse a WatchedItemResponse on 2xx; raise WatcherError otherwise."""
    if resp.is_error:
        raise error_from_response(resp.status_code, resp.content)
    return WatchedItemResponse.from_dict(resp.json())
