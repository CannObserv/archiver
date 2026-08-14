from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watched_item_response import WatchedItemResponse
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/watched-items/{watched_item_id}/restore".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | WatchedItemResponse | None:
    if response.status_code == 200:
        response_200 = WatchedItemResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | WatchedItemResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | WatchedItemResponse]:
    """Restore Watched Item

     Restore the WatchedItem — clears ``archived_at``; re-activates local items.

    On a **reconciled** item (``applied_generation`` set) restore leaves
    ``is_active`` alone (#254 CR-23): the registry owns it, and archive→restore
    was otherwise a two-step bypass of the pause guard — archive flips it False
    locally, restore flipped it True unconditionally, resurrecting an item
    Archiver may have announced paused. The divergence would then be permanent,
    because the snapshot re-announcing the same generation is ignored as stale.
    A restored registry-owned item therefore stays paused until Archiver re-arms
    it — which is the ownership working, not a gap, and the remedy is one click:
    Archiver's ``PUT /info-items/{id}/watch-active`` writes and announces
    **unconditionally**, with no same-value skip, so pressing resume there bumps
    the generation and propagates even when Archiver already considers the item
    active. No pause/resume round-trip is needed.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchedItemResponse]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | WatchedItemResponse | None:
    """Restore Watched Item

     Restore the WatchedItem — clears ``archived_at``; re-activates local items.

    On a **reconciled** item (``applied_generation`` set) restore leaves
    ``is_active`` alone (#254 CR-23): the registry owns it, and archive→restore
    was otherwise a two-step bypass of the pause guard — archive flips it False
    locally, restore flipped it True unconditionally, resurrecting an item
    Archiver may have announced paused. The divergence would then be permanent,
    because the snapshot re-announcing the same generation is ignored as stale.
    A restored registry-owned item therefore stays paused until Archiver re-arms
    it — which is the ownership working, not a gap, and the remedy is one click:
    Archiver's ``PUT /info-items/{id}/watch-active`` writes and announces
    **unconditionally**, with no same-value skip, so pressing resume there bumps
    the generation and propagates even when Archiver already considers the item
    active. No pause/resume round-trip is needed.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchedItemResponse
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | WatchedItemResponse]:
    """Restore Watched Item

     Restore the WatchedItem — clears ``archived_at``; re-activates local items.

    On a **reconciled** item (``applied_generation`` set) restore leaves
    ``is_active`` alone (#254 CR-23): the registry owns it, and archive→restore
    was otherwise a two-step bypass of the pause guard — archive flips it False
    locally, restore flipped it True unconditionally, resurrecting an item
    Archiver may have announced paused. The divergence would then be permanent,
    because the snapshot re-announcing the same generation is ignored as stale.
    A restored registry-owned item therefore stays paused until Archiver re-arms
    it — which is the ownership working, not a gap, and the remedy is one click:
    Archiver's ``PUT /info-items/{id}/watch-active`` writes and announces
    **unconditionally**, with no same-value skip, so pressing resume there bumps
    the generation and propagates even when Archiver already considers the item
    active. No pause/resume round-trip is needed.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchedItemResponse]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | WatchedItemResponse | None:
    """Restore Watched Item

     Restore the WatchedItem — clears ``archived_at``; re-activates local items.

    On a **reconciled** item (``applied_generation`` set) restore leaves
    ``is_active`` alone (#254 CR-23): the registry owns it, and archive→restore
    was otherwise a two-step bypass of the pause guard — archive flips it False
    locally, restore flipped it True unconditionally, resurrecting an item
    Archiver may have announced paused. The divergence would then be permanent,
    because the snapshot re-announcing the same generation is ignored as stale.
    A restored registry-owned item therefore stays paused until Archiver re-arms
    it — which is the ownership working, not a gap, and the remedy is one click:
    Archiver's ``PUT /info-items/{id}/watch-active`` writes and announces
    **unconditionally**, with no same-value skip, so pressing resume there bumps
    the generation and propagates even when Archiver already considers the item
    active. No pause/resume round-trip is needed.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchedItemResponse
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            client=client,
        )
    ).parsed
