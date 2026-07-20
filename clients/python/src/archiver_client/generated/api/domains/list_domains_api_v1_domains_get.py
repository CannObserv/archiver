from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.page_domain_out import PageDomainOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    is_active: bool | None | Unset = UNSET,
    archived: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_is_active: bool | None | Unset
    if isinstance(is_active, Unset):
        json_is_active = UNSET
    else:
        json_is_active = is_active
    params["is_active"] = json_is_active

    json_archived: bool | None | Unset
    if isinstance(archived, Unset):
        json_archived = UNSET
    else:
        json_archived = archived
    params["archived"] = json_archived

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/domains",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | PageDomainOut | None:
    if response.status_code == 200:
        response_200 = PageDomainOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | PageDomainOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    is_active: bool | None | Unset = UNSET,
    archived: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageDomainOut]:
    """List Domains

     List domains with offset pagination.

    Args:
        is_active (bool | None | Unset): Filter by active status.
        archived (bool | None | Unset): When true, return only archived domains.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageDomainOut]
    """

    kwargs = _get_kwargs(
        is_active=is_active,
        archived=archived,
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
    is_active: bool | None | Unset = UNSET,
    archived: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageDomainOut | None:
    """List Domains

     List domains with offset pagination.

    Args:
        is_active (bool | None | Unset): Filter by active status.
        archived (bool | None | Unset): When true, return only archived domains.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageDomainOut
    """

    return sync_detailed(
        client=client,
        is_active=is_active,
        archived=archived,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    is_active: bool | None | Unset = UNSET,
    archived: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageDomainOut]:
    """List Domains

     List domains with offset pagination.

    Args:
        is_active (bool | None | Unset): Filter by active status.
        archived (bool | None | Unset): When true, return only archived domains.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageDomainOut]
    """

    kwargs = _get_kwargs(
        is_active=is_active,
        archived=archived,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    is_active: bool | None | Unset = UNSET,
    archived: bool | None | Unset = UNSET,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageDomainOut | None:
    """List Domains

     List domains with offset pagination.

    Args:
        is_active (bool | None | Unset): Filter by active status.
        archived (bool | None | Unset): When true, return only archived domains.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageDomainOut
    """

    return (
        await asyncio_detailed(
            client=client,
            is_active=is_active,
            archived=archived,
            limit=limit,
            offset=offset,
        )
    ).parsed
