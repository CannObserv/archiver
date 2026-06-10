from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watch_create import WatchCreate
from ...models.watch_response import WatchResponse
from ...types import Response


def _get_kwargs(
    *,
    body: WatchCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/watches",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | WatchResponse | None:
    if response.status_code == 201:
        response_201 = WatchResponse.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | WatchResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: WatchCreate,
) -> Response[HTTPValidationError | WatchResponse]:
    """Create Watch

     Create a Watch under an existing WatchedItem.

    The WatchedItem must already exist with its effective_url set. No Archiver
    SDK calls at Watch-create time (#185 Phase A).

    Error mapping:
    - ``ValueError`` (watched_item_id not found) → 422.

    Args:
        body (WatchCreate): Schema for creating a new Watch.

            The WatchedItem must already exist. No Archiver SDK calls — URL resolution
            is the WatchedItem's responsibility (#185 Phase A).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: WatchCreate,
) -> HTTPValidationError | WatchResponse | None:
    """Create Watch

     Create a Watch under an existing WatchedItem.

    The WatchedItem must already exist with its effective_url set. No Archiver
    SDK calls at Watch-create time (#185 Phase A).

    Error mapping:
    - ``ValueError`` (watched_item_id not found) → 422.

    Args:
        body (WatchCreate): Schema for creating a new Watch.

            The WatchedItem must already exist. No Archiver SDK calls — URL resolution
            is the WatchedItem's responsibility (#185 Phase A).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: WatchCreate,
) -> Response[HTTPValidationError | WatchResponse]:
    """Create Watch

     Create a Watch under an existing WatchedItem.

    The WatchedItem must already exist with its effective_url set. No Archiver
    SDK calls at Watch-create time (#185 Phase A).

    Error mapping:
    - ``ValueError`` (watched_item_id not found) → 422.

    Args:
        body (WatchCreate): Schema for creating a new Watch.

            The WatchedItem must already exist. No Archiver SDK calls — URL resolution
            is the WatchedItem's responsibility (#185 Phase A).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: WatchCreate,
) -> HTTPValidationError | WatchResponse | None:
    """Create Watch

     Create a Watch under an existing WatchedItem.

    The WatchedItem must already exist with its effective_url set. No Archiver
    SDK calls at Watch-create time (#185 Phase A).

    Error mapping:
    - ``ValueError`` (watched_item_id not found) → 422.

    Args:
        body (WatchCreate): Schema for creating a new Watch.

            The WatchedItem must already exist. No Archiver SDK calls — URL resolution
            is the WatchedItem's responsibility (#185 Phase A).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
