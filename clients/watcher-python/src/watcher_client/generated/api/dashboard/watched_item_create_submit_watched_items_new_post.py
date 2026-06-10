from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_watched_item_create_submit_watched_items_new_post import (
    BodyWatchedItemCreateSubmitWatchedItemsNewPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/watched-items/new",
    }

    if not isinstance(body, Unset):
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
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    r"""Watched Item Create Submit

     Create a standalone WatchedItem from the dashboard form.

    Accepts a URL directly; probes it for effective_url + domain_name.
    Audit row uses ``source=\"dashboard\"``.

    Args:
        body (BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
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
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    r"""Watched Item Create Submit

     Create a standalone WatchedItem from the dashboard form.

    Accepts a URL directly; probes it for effective_url + domain_name.
    Audit row uses ``source=\"dashboard\"``.

    Args:
        body (BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    r"""Watched Item Create Submit

     Create a standalone WatchedItem from the dashboard form.

    Accepts a URL directly; probes it for effective_url + domain_name.
    Audit row uses ``source=\"dashboard\"``.

    Args:
        body (BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    r"""Watched Item Create Submit

     Create a standalone WatchedItem from the dashboard form.

    Accepts a URL directly; probes it for effective_url + domain_name.
    Audit row uses ``source=\"dashboard\"``.

    Args:
        body (BodyWatchedItemCreateSubmitWatchedItemsNewPost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
