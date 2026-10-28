from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.list_notification_subscriptions_api_v1_notification_subscriptions_get_scope_type_0 import (
    ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0,
)
from ...models.page_notification_subscription_out import PageNotificationSubscriptionOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    scope: ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    | None
    | Unset = UNSET,
    domain: None | str | Unset = UNSET,
    info_item_id: None | str | Unset = UNSET,
    is_active: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_scope: None | str | Unset
    if isinstance(scope, Unset):
        json_scope = UNSET
    elif isinstance(
        scope, ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    ):
        json_scope = scope.value
    else:
        json_scope = scope
    params["scope"] = json_scope

    json_domain: None | str | Unset
    if isinstance(domain, Unset):
        json_domain = UNSET
    else:
        json_domain = domain
    params["domain"] = json_domain

    json_info_item_id: None | str | Unset
    if isinstance(info_item_id, Unset):
        json_info_item_id = UNSET
    else:
        json_info_item_id = info_item_id
    params["info_item_id"] = json_info_item_id

    json_is_active: bool | None | Unset
    if isinstance(is_active, Unset):
        json_is_active = UNSET
    else:
        json_is_active = is_active
    params["is_active"] = json_is_active

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/notification-subscriptions",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | PageNotificationSubscriptionOut | None:
    if response.status_code == 200:
        response_200 = PageNotificationSubscriptionOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | PageNotificationSubscriptionOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    scope: ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    | None
    | Unset = UNSET,
    domain: None | str | Unset = UNSET,
    info_item_id: None | str | Unset = UNSET,
    is_active: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageNotificationSubscriptionOut]:
    """List Notification Subscriptions

     List subscriptions, oldest first, with offset pagination.

    The filters select rows by their own scope: ``domain`` returns that host's
    domain-scoped rows, not everything that would match an item on it. For
    who hears a given item, see the dashboard's item page.

    Args:
        scope (ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0 | None |
            Unset): Filter by scope.
        domain (None | str | Unset): Filter to domain-scoped subscriptions on this hostname.
        info_item_id (None | str | Unset): Filter to item-scoped subscriptions on this InfoItem.
        is_active (bool | None | Unset): Filter by active status.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageNotificationSubscriptionOut]
    """

    kwargs = _get_kwargs(
        scope=scope,
        domain=domain,
        info_item_id=info_item_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    scope: ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    | None
    | Unset = UNSET,
    domain: None | str | Unset = UNSET,
    info_item_id: None | str | Unset = UNSET,
    is_active: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageNotificationSubscriptionOut | None:
    """List Notification Subscriptions

     List subscriptions, oldest first, with offset pagination.

    The filters select rows by their own scope: ``domain`` returns that host's
    domain-scoped rows, not everything that would match an item on it. For
    who hears a given item, see the dashboard's item page.

    Args:
        scope (ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0 | None |
            Unset): Filter by scope.
        domain (None | str | Unset): Filter to domain-scoped subscriptions on this hostname.
        info_item_id (None | str | Unset): Filter to item-scoped subscriptions on this InfoItem.
        is_active (bool | None | Unset): Filter by active status.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageNotificationSubscriptionOut
    """

    return sync_detailed(
        client=client,
        scope=scope,
        domain=domain,
        info_item_id=info_item_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    scope: ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    | None
    | Unset = UNSET,
    domain: None | str | Unset = UNSET,
    info_item_id: None | str | Unset = UNSET,
    is_active: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageNotificationSubscriptionOut]:
    """List Notification Subscriptions

     List subscriptions, oldest first, with offset pagination.

    The filters select rows by their own scope: ``domain`` returns that host's
    domain-scoped rows, not everything that would match an item on it. For
    who hears a given item, see the dashboard's item page.

    Args:
        scope (ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0 | None |
            Unset): Filter by scope.
        domain (None | str | Unset): Filter to domain-scoped subscriptions on this hostname.
        info_item_id (None | str | Unset): Filter to item-scoped subscriptions on this InfoItem.
        is_active (bool | None | Unset): Filter by active status.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageNotificationSubscriptionOut]
    """

    kwargs = _get_kwargs(
        scope=scope,
        domain=domain,
        info_item_id=info_item_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    scope: ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0
    | None
    | Unset = UNSET,
    domain: None | str | Unset = UNSET,
    info_item_id: None | str | Unset = UNSET,
    is_active: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageNotificationSubscriptionOut | None:
    """List Notification Subscriptions

     List subscriptions, oldest first, with offset pagination.

    The filters select rows by their own scope: ``domain`` returns that host's
    domain-scoped rows, not everything that would match an item on it. For
    who hears a given item, see the dashboard's item page.

    Args:
        scope (ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0 | None |
            Unset): Filter by scope.
        domain (None | str | Unset): Filter to domain-scoped subscriptions on this hostname.
        info_item_id (None | str | Unset): Filter to item-scoped subscriptions on this InfoItem.
        is_active (bool | None | Unset): Filter by active status.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageNotificationSubscriptionOut
    """

    return (
        await asyncio_detailed(
            client=client,
            scope=scope,
            domain=domain,
            info_item_id=info_item_id,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
    ).parsed
