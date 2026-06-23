from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.test_item_notification_api_v1_watched_items_watched_item_id_notifications_template_id_test_post_response_test_item_notification_api_v1_watched_items_watched_item_id_notifications_template_id_test_post import (
    TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost,
)
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
    template_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/watched-items/{watched_item_id}/notifications/{template_id}/test".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
            template_id=quote(str(template_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
    | None
):
    if response.status_code == 200:
        response_200 = TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost.from_dict(
            response.json()
        )

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
) -> Response[
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
]:
    """Test Item Notification

     Send a test notification for an item-scoped template via the notifier service.

    Returns {success, reason}, never 5xx.

    Args:
        watched_item_id (str):
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        template_id=template_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
    | None
):
    """Test Item Notification

     Send a test notification for an item-scoped template via the notifier service.

    Returns {success, reason}, never 5xx.

    Args:
        watched_item_id (str):
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        template_id=template_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
]:
    """Test Item Notification

     Send a test notification for an item-scoped template via the notifier service.

    Returns {success, reason}, never 5xx.

    Args:
        watched_item_id (str):
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        template_id=template_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
    | None
):
    """Test Item Notification

     Send a test notification for an item-scoped template via the notifier service.

    Returns {success, reason}, never 5xx.

    Args:
        watched_item_id (str):
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPostResponseTestItemNotificationApiV1WatchedItemsWatchedItemIdNotificationsTemplateIdTestPost
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            template_id=template_id,
            client=client,
        )
    ).parsed
