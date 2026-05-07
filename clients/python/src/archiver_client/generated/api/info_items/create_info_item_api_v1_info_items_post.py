from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.info_item_create import InfoItemCreate
from ...models.info_item_with_spec_out import InfoItemWithSpecOut
from ...types import Response


def _get_kwargs(
    *,
    body: InfoItemCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/info-items",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InfoItemWithSpecOut | None:
    if response.status_code == 201:
        response_201 = InfoItemWithSpecOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | InfoItemWithSpecOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: InfoItemCreate,
) -> Response[HTTPValidationError | InfoItemWithSpecOut]:
    """Create Info Item

     Create an InfoItem.

    When ``initial_info_spec`` is supplied, validate it first; on success,
    create both the InfoItem and a primary (priority=1, active=True) InfoSpec
    in a single transaction. On validation failure, neither row is written.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemWithSpecOut]
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
    client: AuthenticatedClient,
    body: InfoItemCreate,
) -> HTTPValidationError | InfoItemWithSpecOut | None:
    """Create Info Item

     Create an InfoItem.

    When ``initial_info_spec`` is supplied, validate it first; on success,
    create both the InfoItem and a primary (priority=1, active=True) InfoSpec
    in a single transaction. On validation failure, neither row is written.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemWithSpecOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: InfoItemCreate,
) -> Response[HTTPValidationError | InfoItemWithSpecOut]:
    """Create Info Item

     Create an InfoItem.

    When ``initial_info_spec`` is supplied, validate it first; on success,
    create both the InfoItem and a primary (priority=1, active=True) InfoSpec
    in a single transaction. On validation failure, neither row is written.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemWithSpecOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: InfoItemCreate,
) -> HTTPValidationError | InfoItemWithSpecOut | None:
    """Create Info Item

     Create an InfoItem.

    When ``initial_info_spec`` is supplied, validate it first; on success,
    create both the InfoItem and a primary (priority=1, active=True) InfoSpec
    in a single transaction. On validation failure, neither row is written.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemWithSpecOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
