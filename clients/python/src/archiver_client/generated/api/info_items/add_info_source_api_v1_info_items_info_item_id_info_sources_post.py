from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.info_item_source_create import InfoItemSourceCreate
from ...models.info_item_source_out import InfoItemSourceOut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemSourceCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/info-items/{info_item_id}/info-sources".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InfoItemSourceOut | None:
    if response.status_code == 201:
        response_201 = InfoItemSourceOut.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | InfoItemSourceOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemSourceCreate,
) -> Response[HTTPValidationError | InfoItemSourceOut]:
    """Add Info Source

     Declare a binding between an InfoItem and an existing InfoSource.

    Looks up both entities; returns 404 if either doesn't exist. The binding
    is a new ``info_item_sources`` row with the requested role.

    Args:
        info_item_id (str):
        body (InfoItemSourceCreate): Request body for POST /info-items/{id}/info-sources.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemSourceOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemSourceCreate,
) -> HTTPValidationError | InfoItemSourceOut | None:
    """Add Info Source

     Declare a binding between an InfoItem and an existing InfoSource.

    Looks up both entities; returns 404 if either doesn't exist. The binding
    is a new ``info_item_sources`` row with the requested role.

    Args:
        info_item_id (str):
        body (InfoItemSourceCreate): Request body for POST /info-items/{id}/info-sources.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemSourceOut
    """

    return sync_detailed(
        info_item_id=info_item_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemSourceCreate,
) -> Response[HTTPValidationError | InfoItemSourceOut]:
    """Add Info Source

     Declare a binding between an InfoItem and an existing InfoSource.

    Looks up both entities; returns 404 if either doesn't exist. The binding
    is a new ``info_item_sources`` row with the requested role.

    Args:
        info_item_id (str):
        body (InfoItemSourceCreate): Request body for POST /info-items/{id}/info-sources.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemSourceOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemSourceCreate,
) -> HTTPValidationError | InfoItemSourceOut | None:
    """Add Info Source

     Declare a binding between an InfoItem and an existing InfoSource.

    Looks up both entities; returns 404 if either doesn't exist. The binding
    is a new ``info_item_sources`` row with the requested role.

    Args:
        info_item_id (str):
        body (InfoItemSourceCreate): Request body for POST /info-items/{id}/info-sources.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemSourceOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
            body=body,
        )
    ).parsed
