from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.notification_subscription_create import NotificationSubscriptionCreate
from ...models.notification_subscription_out import NotificationSubscriptionOut
from ...types import Response


def _get_kwargs(
    *,
    body: NotificationSubscriptionCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/notification-subscriptions",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    if response.status_code == 201:
        response_201 = NotificationSubscriptionOut.from_dict(response.json())

        return response_201

    if response.status_code == 400:
        response_400 = EnvelopeResponse.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = EnvelopeResponse.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = EnvelopeResponse.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = EnvelopeResponse.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = EnvelopeResponse.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = EnvelopeResponse.from_dict(response.json())

        return response_422

    if response.status_code == 500:
        response_500 = EnvelopeResponse.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[EnvelopeResponse | NotificationSubscriptionOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionCreate,
) -> Response[EnvelopeResponse | NotificationSubscriptionOut]:
    """Create Notification Subscription

     Create a subscription.

    ``scope`` takes exactly its ref (``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``); a ref that does not fit, or names no row, is
    a 422 on that field. A duplicate ``imported_watcher_id`` is a 409.

    Args:
        body (NotificationSubscriptionCreate): Request body for POST /notification-subscriptions.

            ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
            ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
            create; re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | NotificationSubscriptionOut]
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
    body: NotificationSubscriptionCreate,
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    """Create Notification Subscription

     Create a subscription.

    ``scope`` takes exactly its ref (``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``); a ref that does not fit, or names no row, is
    a 422 on that field. A duplicate ``imported_watcher_id`` is a 409.

    Args:
        body (NotificationSubscriptionCreate): Request body for POST /notification-subscriptions.

            ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
            ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
            create; re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | NotificationSubscriptionOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionCreate,
) -> Response[EnvelopeResponse | NotificationSubscriptionOut]:
    """Create Notification Subscription

     Create a subscription.

    ``scope`` takes exactly its ref (``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``); a ref that does not fit, or names no row, is
    a 422 on that field. A duplicate ``imported_watcher_id`` is a 409.

    Args:
        body (NotificationSubscriptionCreate): Request body for POST /notification-subscriptions.

            ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
            ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
            create; re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | NotificationSubscriptionOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionCreate,
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    """Create Notification Subscription

     Create a subscription.

    ``scope`` takes exactly its ref (``domain`` a hostname with a Domain row,
    ``item`` an ``info_item_id``); a ref that does not fit, or names no row, is
    a 422 on that field. A duplicate ``imported_watcher_id`` is a 409.

    Args:
        body (NotificationSubscriptionCreate): Request body for POST /notification-subscriptions.

            ``scope`` takes exactly its ref: ``domain`` a hostname with a Domain row,
            ``item`` an ``info_item_id``, ``global`` neither. Both are fixed after
            create; re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | NotificationSubscriptionOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
