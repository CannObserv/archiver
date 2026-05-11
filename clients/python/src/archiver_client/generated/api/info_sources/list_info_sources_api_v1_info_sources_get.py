from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.page_info_source_out import PageInfoSourceOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    parent_info_source_id: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_parent_info_source_id: None | str | Unset
    if isinstance(parent_info_source_id, Unset):
        json_parent_info_source_id = UNSET
    else:
        json_parent_info_source_id = parent_info_source_id
    params["parent_info_source_id"] = json_parent_info_source_id

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/info-sources",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | PageInfoSourceOut | None:
    if response.status_code == 200:
        response_200 = PageInfoSourceOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | PageInfoSourceOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    parent_info_source_id: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[HTTPValidationError | PageInfoSourceOut]:
    """List Info Sources

     List InfoSources with offset pagination, optionally filtered by parent.

    Without ``parent_info_source_id`` returns all rows. With it, returns only
    fragments whose ``parent_info_source_id`` matches. ``has_more`` is derived
    via a ``limit+1`` probe; no total count is computed.

    Args:
        parent_info_source_id (None | str | Unset):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageInfoSourceOut]
    """

    kwargs = _get_kwargs(
        parent_info_source_id=parent_info_source_id,
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
    parent_info_source_id: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> HTTPValidationError | PageInfoSourceOut | None:
    """List Info Sources

     List InfoSources with offset pagination, optionally filtered by parent.

    Without ``parent_info_source_id`` returns all rows. With it, returns only
    fragments whose ``parent_info_source_id`` matches. ``has_more`` is derived
    via a ``limit+1`` probe; no total count is computed.

    Args:
        parent_info_source_id (None | str | Unset):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageInfoSourceOut
    """

    return sync_detailed(
        client=client,
        parent_info_source_id=parent_info_source_id,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    parent_info_source_id: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[HTTPValidationError | PageInfoSourceOut]:
    """List Info Sources

     List InfoSources with offset pagination, optionally filtered by parent.

    Without ``parent_info_source_id`` returns all rows. With it, returns only
    fragments whose ``parent_info_source_id`` matches. ``has_more`` is derived
    via a ``limit+1`` probe; no total count is computed.

    Args:
        parent_info_source_id (None | str | Unset):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | PageInfoSourceOut]
    """

    kwargs = _get_kwargs(
        parent_info_source_id=parent_info_source_id,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    parent_info_source_id: None | str | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> HTTPValidationError | PageInfoSourceOut | None:
    """List Info Sources

     List InfoSources with offset pagination, optionally filtered by parent.

    Without ``parent_info_source_id`` returns all rows. With it, returns only
    fragments whose ``parent_info_source_id`` matches. ``has_more`` is derived
    via a ``limit+1`` probe; no total count is computed.

    Args:
        parent_info_source_id (None | str | Unset):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | PageInfoSourceOut
    """

    return (
        await asyncio_detailed(
            client=client,
            parent_info_source_id=parent_info_source_id,
            limit=limit,
            offset=offset,
        )
    ).parsed
