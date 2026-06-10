from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watch_response import WatchResponse
from ...types import Response


def _get_kwargs(
    watch_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/watches/{watch_id}/deactivate".format(
            watch_id=quote(str(watch_id), safe=""),
        ),
    }

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
) -> Response[HTTPValidationError | WatchResponse]:
    """Deactivate Watch

     Deactivate a watch without deleting it.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | WatchResponse | None:
    """Deactivate Watch

     Deactivate a watch without deleting it.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchResponse
    """

    return sync_detailed(
        watch_id=watch_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | WatchResponse]:
    """Deactivate Watch

     Deactivate a watch without deleting it.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | WatchResponse | None:
    """Deactivate Watch

     Deactivate a watch without deleting it.

    Args:
        watch_id (str):

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
        )
    ).parsed
