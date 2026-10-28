from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.notification_subscription_out import NotificationSubscriptionOut
from ...models.notification_subscription_patch import NotificationSubscriptionPatch
from ...types import Response


def _get_kwargs(
    subscription_id: str,
    *,
    body: NotificationSubscriptionPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/notification-subscriptions/{subscription_id}".format(
            subscription_id=quote(str(subscription_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    if response.status_code == 200:
        response_200 = NotificationSubscriptionOut.from_dict(response.json())

        return response_200

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
    subscription_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionPatch,
) -> Response[EnvelopeResponse | NotificationSubscriptionOut]:
    """Update Notification Subscription

     Change the fields sent. ``content_config`` is replaced whole (``null`` =
    all defaults). The scope, its ref and ``imported_watcher_id`` are fixed:
    re-scope by deleting and creating.

    Args:
        subscription_id (str):
        body (NotificationSubscriptionPatch): Request body for PATCH /notification-
            subscriptions/{id}.

            Only the fields sent change. ``content_config`` is replaced whole, and
            ``null`` returns it to all defaults. The scope, its ref and
            ``imported_watcher_id`` are refused: re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | NotificationSubscriptionOut]
    """

    kwargs = _get_kwargs(
        subscription_id=subscription_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    subscription_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionPatch,
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    """Update Notification Subscription

     Change the fields sent. ``content_config`` is replaced whole (``null`` =
    all defaults). The scope, its ref and ``imported_watcher_id`` are fixed:
    re-scope by deleting and creating.

    Args:
        subscription_id (str):
        body (NotificationSubscriptionPatch): Request body for PATCH /notification-
            subscriptions/{id}.

            Only the fields sent change. ``content_config`` is replaced whole, and
            ``null`` returns it to all defaults. The scope, its ref and
            ``imported_watcher_id`` are refused: re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | NotificationSubscriptionOut
    """

    return sync_detailed(
        subscription_id=subscription_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    subscription_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionPatch,
) -> Response[EnvelopeResponse | NotificationSubscriptionOut]:
    """Update Notification Subscription

     Change the fields sent. ``content_config`` is replaced whole (``null`` =
    all defaults). The scope, its ref and ``imported_watcher_id`` are fixed:
    re-scope by deleting and creating.

    Args:
        subscription_id (str):
        body (NotificationSubscriptionPatch): Request body for PATCH /notification-
            subscriptions/{id}.

            Only the fields sent change. ``content_config`` is replaced whole, and
            ``null`` returns it to all defaults. The scope, its ref and
            ``imported_watcher_id`` are refused: re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | NotificationSubscriptionOut]
    """

    kwargs = _get_kwargs(
        subscription_id=subscription_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    subscription_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationSubscriptionPatch,
) -> EnvelopeResponse | NotificationSubscriptionOut | None:
    """Update Notification Subscription

     Change the fields sent. ``content_config`` is replaced whole (``null`` =
    all defaults). The scope, its ref and ``imported_watcher_id`` are fixed:
    re-scope by deleting and creating.

    Args:
        subscription_id (str):
        body (NotificationSubscriptionPatch): Request body for PATCH /notification-
            subscriptions/{id}.

            Only the fields sent change. ``content_config`` is replaced whole, and
            ``null`` returns it to all defaults. The scope, its ref and
            ``imported_watcher_id`` are refused: re-scope by deleting and creating.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | NotificationSubscriptionOut
    """

    return (
        await asyncio_detailed(
            subscription_id=subscription_id,
            client=client,
            body=body,
        )
    ).parsed
