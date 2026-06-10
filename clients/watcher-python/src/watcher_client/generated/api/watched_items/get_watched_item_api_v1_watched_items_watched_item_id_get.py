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
        "method": "get",
        "url": "/api/v1/watched-items/{watched_item_id}".format(
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
    """Get Watched Item

     Fetch a single WatchedItem by ID.

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
    """Get Watched Item

     Fetch a single WatchedItem by ID.

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
    """Get Watched Item

     Fetch a single WatchedItem by ID.

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
    """Get Watched Item

     Fetch a single WatchedItem by ID.

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
