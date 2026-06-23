from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.notification_template_response import NotificationTemplateResponse
from ...models.notification_template_update import NotificationTemplateUpdate
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
    template_id: str,
    *,
    body: NotificationTemplateUpdate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/watched-items/{watched_item_id}/notifications/{template_id}".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
            template_id=quote(str(template_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | NotificationTemplateResponse | None:
    if response.status_code == 200:
        response_200 = NotificationTemplateResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
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
    body: NotificationTemplateUpdate,
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
    """Update Item Notification

     Update an item-scoped template's mutable fields.

    Args:
        watched_item_id (str):
        template_id (str):
        body (NotificationTemplateUpdate): Partial update. ``visibility`` and its refs are
            intrinsic and not updatable
            here — re-scoping a template means delete + recreate.

            ``channel_hint`` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | NotificationTemplateResponse]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        template_id=template_id,
        body=body,
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
    body: NotificationTemplateUpdate,
) -> HTTPValidationError | NotificationTemplateResponse | None:
    """Update Item Notification

     Update an item-scoped template's mutable fields.

    Args:
        watched_item_id (str):
        template_id (str):
        body (NotificationTemplateUpdate): Partial update. ``visibility`` and its refs are
            intrinsic and not updatable
            here — re-scoping a template means delete + recreate.

            ``channel_hint`` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | NotificationTemplateResponse
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        template_id=template_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateUpdate,
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
    """Update Item Notification

     Update an item-scoped template's mutable fields.

    Args:
        watched_item_id (str):
        template_id (str):
        body (NotificationTemplateUpdate): Partial update. ``visibility`` and its refs are
            intrinsic and not updatable
            here — re-scoping a template means delete + recreate.

            ``channel_hint`` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | NotificationTemplateResponse]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        template_id=template_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    template_id: str,
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateUpdate,
) -> HTTPValidationError | NotificationTemplateResponse | None:
    """Update Item Notification

     Update an item-scoped template's mutable fields.

    Args:
        watched_item_id (str):
        template_id (str):
        body (NotificationTemplateUpdate): Partial update. ``visibility`` and its refs are
            intrinsic and not updatable
            here — re-scoping a template means delete + recreate.

            ``channel_hint`` stays nullable on Update so the route can use
            ``model_fields_set`` to distinguish "not provided" (no-op) from a
            user-supplied value. Same pattern as ``title``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | NotificationTemplateResponse
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            template_id=template_id,
            client=client,
            body=body,
        )
    ).parsed
