from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watch_notification_config_response import WatchNotificationConfigResponse
from ...types import Response


def _get_kwargs(
    watch_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/watches/{watch_id}/notifications".format(
            watch_id=quote(str(watch_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[WatchNotificationConfigResponse] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = WatchNotificationConfigResponse.from_dict(response_200_item_data)

            response_200.append(response_200_item)

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
) -> Response[HTTPValidationError | list[WatchNotificationConfigResponse]]:
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
) -> Response[HTTPValidationError | list[WatchNotificationConfigResponse]]:
    """List Notification Configs

     List notification configs for a watch.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[WatchNotificationConfigResponse]]
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
) -> HTTPValidationError | list[WatchNotificationConfigResponse] | None:
    """List Notification Configs

     List notification configs for a watch.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[WatchNotificationConfigResponse]
    """

    return sync_detailed(
        watch_id=watch_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | list[WatchNotificationConfigResponse]]:
    """List Notification Configs

     List notification configs for a watch.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[WatchNotificationConfigResponse]]
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
) -> HTTPValidationError | list[WatchNotificationConfigResponse] | None:
    """List Notification Configs

     List notification configs for a watch.

    Args:
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[WatchNotificationConfigResponse]
    """

    return (
        await asyncio_detailed(
            watch_id=watch_id,
            client=client,
        )
    ).parsed
