from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watch_notification_config_response import WatchNotificationConfigResponse
from ...models.watch_notification_config_update import WatchNotificationConfigUpdate
from ...types import Response


def _get_kwargs(
    watch_id: str,
    config_id: str,
    *,
    body: WatchNotificationConfigUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/watches/{watch_id}/notifications/{config_id}".format(
            watch_id=quote(str(watch_id), safe=""),
            config_id=quote(str(config_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | WatchNotificationConfigResponse | None:
    if response.status_code == 200:
        response_200 = WatchNotificationConfigResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | WatchNotificationConfigResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watch_id: str,
    config_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchNotificationConfigUpdate,
) -> Response[HTTPValidationError | WatchNotificationConfigResponse]:
    """Update Notification Config

     Update is_active, events, channel_hint, or remote_channel_id on a notification config.

    Args:
        watch_id (str):
        config_id (str):
        body (WatchNotificationConfigUpdate): Request body for PATCH — all fields optional.

            `channel_hint` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``. The Create schema
            is `str` (always present, default `"remote"`) — the asymmetry is
            intentional.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchNotificationConfigResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        config_id=config_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watch_id: str,
    config_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchNotificationConfigUpdate,
) -> HTTPValidationError | WatchNotificationConfigResponse | None:
    """Update Notification Config

     Update is_active, events, channel_hint, or remote_channel_id on a notification config.

    Args:
        watch_id (str):
        config_id (str):
        body (WatchNotificationConfigUpdate): Request body for PATCH — all fields optional.

            `channel_hint` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``. The Create schema
            is `str` (always present, default `"remote"`) — the asymmetry is
            intentional.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchNotificationConfigResponse
    """

    return sync_detailed(
        watch_id=watch_id,
        config_id=config_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    watch_id: str,
    config_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchNotificationConfigUpdate,
) -> Response[HTTPValidationError | WatchNotificationConfigResponse]:
    """Update Notification Config

     Update is_active, events, channel_hint, or remote_channel_id on a notification config.

    Args:
        watch_id (str):
        config_id (str):
        body (WatchNotificationConfigUpdate): Request body for PATCH — all fields optional.

            `channel_hint` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``. The Create schema
            is `str` (always present, default `"remote"`) — the asymmetry is
            intentional.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchNotificationConfigResponse]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        config_id=config_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watch_id: str,
    config_id: str,
    *,
    client: AuthenticatedClient,
    body: WatchNotificationConfigUpdate,
) -> HTTPValidationError | WatchNotificationConfigResponse | None:
    """Update Notification Config

     Update is_active, events, channel_hint, or remote_channel_id on a notification config.

    Args:
        watch_id (str):
        config_id (str):
        body (WatchNotificationConfigUpdate): Request body for PATCH — all fields optional.

            `channel_hint` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``. The Create schema
            is `str` (always present, default `"remote"`) — the asymmetry is
            intentional.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchNotificationConfigResponse
    """

    return (
        await asyncio_detailed(
            watch_id=watch_id,
            config_id=config_id,
            client=client,
            body=body,
        )
    ).parsed
