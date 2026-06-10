from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_watched_item_template_update_watched_items_watched_item_id_templates_tpl_id_post import (
    BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
    tpl_id: str,
    *,
    body: BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/watched-items/{watched_item_id}/templates/{tpl_id}".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
            tpl_id=quote(str(tpl_id), safe=""),
        ),
    }

    _kwargs["data"] = body.to_dict()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = response.json()
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
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watched_item_id: str,
    tpl_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Template Update

    Args:
        watched_item_id (str):
        tpl_id (str):
        body (BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        tpl_id=tpl_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    tpl_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
) -> Any | HTTPValidationError | None:
    """Watched Item Template Update

    Args:
        watched_item_id (str):
        tpl_id (str):
        body (BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        tpl_id=tpl_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    tpl_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Template Update

    Args:
        watched_item_id (str):
        tpl_id (str):
        body (BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        tpl_id=tpl_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    tpl_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost,
) -> Any | HTTPValidationError | None:
    """Watched Item Template Update

    Args:
        watched_item_id (str):
        tpl_id (str):
        body (BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            tpl_id=tpl_id,
            client=client,
            body=body,
        )
    ).parsed
