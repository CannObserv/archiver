from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    watched_item_id: str,
    *,
    event_type: list[str] | Unset = UNSET,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_event_type: list[str] | Unset = UNSET
    if not isinstance(event_type, Unset):
        json_event_type = event_type

    params["event_type"] = json_event_type

    params["page"] = page

    params["page_size"] = page_size

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/watched-items/{watched_item_id}".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
        ),
        "params": params,
    }

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
    *,
    client: AuthenticatedClient | Client,
    event_type: list[str] | Unset = UNSET,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Detail Page

     Detail page for a WatchedItem.

    Args:
        watched_item_id (str):
        event_type (list[str] | Unset):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    event_type: list[str] | Unset = UNSET,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Any | HTTPValidationError | None:
    """Watched Item Detail Page

     Detail page for a WatchedItem.

    Args:
        watched_item_id (str):
        event_type (list[str] | Unset):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        client=client,
        event_type=event_type,
        page=page,
        page_size=page_size,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    event_type: list[str] | Unset = UNSET,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Detail Page

     Detail page for a WatchedItem.

    Args:
        watched_item_id (str):
        event_type (list[str] | Unset):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    event_type: list[str] | Unset = UNSET,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Any | HTTPValidationError | None:
    """Watched Item Detail Page

     Detail page for a WatchedItem.

    Args:
        watched_item_id (str):
        event_type (list[str] | Unset):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            client=client,
            event_type=event_type,
            page=page,
            page_size=page_size,
        )
    ).parsed
