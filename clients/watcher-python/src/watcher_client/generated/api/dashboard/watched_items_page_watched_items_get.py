from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    q: None | str | Unset = UNSET,
    include_archived: bool | Unset = False,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_q: None | str | Unset
    if isinstance(q, Unset):
        json_q = UNSET
    else:
        json_q = q
    params["q"] = json_q

    params["include_archived"] = include_archived

    params["page"] = page

    params["page_size"] = page_size

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/watched-items",
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
    *,
    client: AuthenticatedClient | Client,
    q: None | str | Unset = UNSET,
    include_archived: bool | Unset = False,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Response[Any | HTTPValidationError]:
    """Watched Items Page

     List page for WatchedItems.

    Args:
        q (None | str | Unset):
        include_archived (bool | Unset):  Default: False.
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        q=q,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    q: None | str | Unset = UNSET,
    include_archived: bool | Unset = False,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Any | HTTPValidationError | None:
    """Watched Items Page

     List page for WatchedItems.

    Args:
        q (None | str | Unset):
        include_archived (bool | Unset):  Default: False.
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        q=q,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    q: None | str | Unset = UNSET,
    include_archived: bool | Unset = False,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Response[Any | HTTPValidationError]:
    """Watched Items Page

     List page for WatchedItems.

    Args:
        q (None | str | Unset):
        include_archived (bool | Unset):  Default: False.
        page (int | Unset):  Default: 1.
        page_size (int | Unset):  Default: 25.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        q=q,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    q: None | str | Unset = UNSET,
    include_archived: bool | Unset = False,
    page: int | Unset = 1,
    page_size: int | Unset = 25,
) -> Any | HTTPValidationError | None:
    """Watched Items Page

     List page for WatchedItems.

    Args:
        q (None | str | Unset):
        include_archived (bool | Unset):  Default: False.
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
            client=client,
            q=q,
            include_archived=include_archived,
            page=page,
            page_size=page_size,
        )
    ).parsed
