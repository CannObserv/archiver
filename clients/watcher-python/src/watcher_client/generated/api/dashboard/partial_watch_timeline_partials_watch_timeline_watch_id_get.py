from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    watch_id: str,
    *,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
    category: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["page"] = page

    params["page_size"] = page_size

    json_category: None | str | Unset
    if isinstance(category, Unset):
        json_category = UNSET
    else:
        json_category = category
    params["category"] = json_category

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/partials/watch-timeline/{watch_id}".format(
            watch_id=quote(str(watch_id), safe=""),
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
    watch_id: str,
    *,
    client: AuthenticatedClient | Client,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
    category: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Partial Watch Timeline

     HTMX partial: unified lifecycle event timeline for a watch.

    Args:
        watch_id (str):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.
        category (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        page=page,
        page_size=page_size,
        category=category,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watch_id: str,
    *,
    client: AuthenticatedClient | Client,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
    category: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Partial Watch Timeline

     HTMX partial: unified lifecycle event timeline for a watch.

    Args:
        watch_id (str):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.
        category (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        watch_id=watch_id,
        client=client,
        page=page,
        page_size=page_size,
        category=category,
    ).parsed


async def asyncio_detailed(
    watch_id: str,
    *,
    client: AuthenticatedClient | Client,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
    category: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Partial Watch Timeline

     HTMX partial: unified lifecycle event timeline for a watch.

    Args:
        watch_id (str):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.
        category (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watch_id=watch_id,
        page=page,
        page_size=page_size,
        category=category,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watch_id: str,
    *,
    client: AuthenticatedClient | Client,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
    category: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Partial Watch Timeline

     HTMX partial: unified lifecycle event timeline for a watch.

    Args:
        watch_id (str):
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.
        category (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            watch_id=watch_id,
            client=client,
            page=page,
            page_size=page_size,
            category=category,
        )
    ).parsed
