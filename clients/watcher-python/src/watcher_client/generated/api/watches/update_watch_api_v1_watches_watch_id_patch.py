from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watch_response import WatchResponse
from ...models.watch_update import WatchUpdate
from ...types import Response


def _get_kwargs(
    watch_id: str,
    *,
    body: WatchUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/watches/{watch_id}".format(
            watch_id=quote(str(watch_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | WatchResponse | None:
    if response.status_code == 200:
        response_200 = WatchResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | WatchResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watch_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchUpdate,
) -> Response[HTTPValidationError | WatchResponse]:
    """Update Watch

     Update a watch. Only provided fields are changed.

    Args:
        watch_id (str):
        body (WatchUpdate): Schema for updating a Watch. All fields optional.

            Identity fields (info_item_id) are immutable after creation — re-target
            by deleting and recreating the Watch.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watch_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchUpdate,
) -> HTTPValidationError | WatchResponse | None:
    """Update Watch

     Update a watch. Only provided fields are changed.

    Args:
        watch_id (str):
        body (WatchUpdate): Schema for updating a Watch. All fields optional.

            Identity fields (info_item_id) are immutable after creation — re-target
            by deleting and recreating the Watch.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchResponse
    """

    return sync_detailed(
        watch_id=watch_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    watch_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchUpdate,
) -> Response[HTTPValidationError | WatchResponse]:
    """Update Watch

     Update a watch. Only provided fields are changed.

    Args:
        watch_id (str):
        body (WatchUpdate): Schema for updating a Watch. All fields optional.

            Identity fields (info_item_id) are immutable after creation — re-target
            by deleting and recreating the Watch.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watch_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchUpdate,
) -> HTTPValidationError | WatchResponse | None:
    """Update Watch

     Update a watch. Only provided fields are changed.

    Args:
        watch_id (str):
        body (WatchUpdate): Schema for updating a Watch. All fields optional.

            Identity fields (info_item_id) are immutable after creation — re-target
            by deleting and recreating the Watch.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchResponse
    """

    return (
        await asyncio_detailed(
            watch_id=watch_id,
            client=client,
            body=body,
        )
    ).parsed
