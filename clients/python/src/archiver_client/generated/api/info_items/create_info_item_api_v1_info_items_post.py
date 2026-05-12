from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_create import InfoItemCreate
from ...models.info_item_out import InfoItemOut
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
) -> EnvelopeResponse | InfoItemOut | None:
    if response.status_code == 201:
        response_201 = InfoItemOut.from_dict(response.json())

        return response_201

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
) -> Response[EnvelopeResponse | InfoItemOut]:
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
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Create Info Item

     Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemOut]
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
) -> EnvelopeResponse | InfoItemOut | None:
    """Create Info Item

     Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: InfoItemCreate,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Create Info Item

     Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemOut]
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
) -> EnvelopeResponse | InfoItemOut | None:
    """Create Info Item

     Create an InfoItem.

    Optionally accepts ``initial_source_spec`` (creates a primary InfoSource
    binding) and ``initial_rep_spec_assignments`` (creates effective-dated
    RepSpec assignments). All writes are a single transaction; any validation
    or lookup failure rolls back the whole thing.

    Args:
        body (InfoItemCreate):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
