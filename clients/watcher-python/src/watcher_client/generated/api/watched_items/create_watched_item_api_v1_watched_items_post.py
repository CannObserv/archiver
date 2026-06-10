from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watched_item_create import WatchedItemCreate
from ...models.watched_item_response import WatchedItemResponse
from ...types import Response


def _get_kwargs(
    *,
    body: WatchedItemCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/watched-items",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | WatchedItemResponse | None:
    if response.status_code == 201:
        response_201 = WatchedItemResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | WatchedItemResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: WatchedItemCreate,
) -> Response[HTTPValidationError | WatchedItemResponse]:
    """Create Watched Item

     Create a standalone WatchedItem.

    Two paths depending on which anchor is provided:

    **InfoItem-linked** (``archiver_info_item_id`` set): validates the InfoItem via the
    Archiver SDK; name defaults to the InfoItem's name.
    Errors: NotFound → 422, AuthError → 500, ServerError/network → 503.

    **URL-only** (``url`` set, no ``archiver_info_item_id``): probes the URL for
    ``effective_url`` + ``domain_name``; name defaults to the probed domain.
    ``archiver_info_item_id`` is null on the resulting record.
    Error: unreachable URL → 422.

    At least one of ``archiver_info_item_id`` or ``url`` is required (schema-enforced).

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            Two creation paths:
            - **InfoItem-linked** (``archiver_info_item_id`` provided): the InfoItem's existence
              is validated via the Archiver SDK (NotFound → 422); name defaults to the
              InfoItem's name when omitted.
            - **URL-only** (``url`` provided, no ``archiver_info_item_id``): the URL is probed
              for ``effective_url`` + ``domain_name``; name defaults to the probed
              domain. Produces a WatchedItem with ``archiver_info_item_id=None`` (#185 Phase A).

            At least one of ``archiver_info_item_id`` or ``url`` is required.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchedItemResponse]
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
    body: WatchedItemCreate,
) -> HTTPValidationError | WatchedItemResponse | None:
    """Create Watched Item

     Create a standalone WatchedItem.

    Two paths depending on which anchor is provided:

    **InfoItem-linked** (``archiver_info_item_id`` set): validates the InfoItem via the
    Archiver SDK; name defaults to the InfoItem's name.
    Errors: NotFound → 422, AuthError → 500, ServerError/network → 503.

    **URL-only** (``url`` set, no ``archiver_info_item_id``): probes the URL for
    ``effective_url`` + ``domain_name``; name defaults to the probed domain.
    ``archiver_info_item_id`` is null on the resulting record.
    Error: unreachable URL → 422.

    At least one of ``archiver_info_item_id`` or ``url`` is required (schema-enforced).

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            Two creation paths:
            - **InfoItem-linked** (``archiver_info_item_id`` provided): the InfoItem's existence
              is validated via the Archiver SDK (NotFound → 422); name defaults to the
              InfoItem's name when omitted.
            - **URL-only** (``url`` provided, no ``archiver_info_item_id``): the URL is probed
              for ``effective_url`` + ``domain_name``; name defaults to the probed
              domain. Produces a WatchedItem with ``archiver_info_item_id=None`` (#185 Phase A).

            At least one of ``archiver_info_item_id`` or ``url`` is required.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchedItemResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: WatchedItemCreate,
) -> Response[HTTPValidationError | WatchedItemResponse]:
    """Create Watched Item

     Create a standalone WatchedItem.

    Two paths depending on which anchor is provided:

    **InfoItem-linked** (``archiver_info_item_id`` set): validates the InfoItem via the
    Archiver SDK; name defaults to the InfoItem's name.
    Errors: NotFound → 422, AuthError → 500, ServerError/network → 503.

    **URL-only** (``url`` set, no ``archiver_info_item_id``): probes the URL for
    ``effective_url`` + ``domain_name``; name defaults to the probed domain.
    ``archiver_info_item_id`` is null on the resulting record.
    Error: unreachable URL → 422.

    At least one of ``archiver_info_item_id`` or ``url`` is required (schema-enforced).

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            Two creation paths:
            - **InfoItem-linked** (``archiver_info_item_id`` provided): the InfoItem's existence
              is validated via the Archiver SDK (NotFound → 422); name defaults to the
              InfoItem's name when omitted.
            - **URL-only** (``url`` provided, no ``archiver_info_item_id``): the URL is probed
              for ``effective_url`` + ``domain_name``; name defaults to the probed
              domain. Produces a WatchedItem with ``archiver_info_item_id=None`` (#185 Phase A).

            At least one of ``archiver_info_item_id`` or ``url`` is required.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | WatchedItemResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: WatchedItemCreate,
) -> HTTPValidationError | WatchedItemResponse | None:
    """Create Watched Item

     Create a standalone WatchedItem.

    Two paths depending on which anchor is provided:

    **InfoItem-linked** (``archiver_info_item_id`` set): validates the InfoItem via the
    Archiver SDK; name defaults to the InfoItem's name.
    Errors: NotFound → 422, AuthError → 500, ServerError/network → 503.

    **URL-only** (``url`` set, no ``archiver_info_item_id``): probes the URL for
    ``effective_url`` + ``domain_name``; name defaults to the probed domain.
    ``archiver_info_item_id`` is null on the resulting record.
    Error: unreachable URL → 422.

    At least one of ``archiver_info_item_id`` or ``url`` is required (schema-enforced).

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            Two creation paths:
            - **InfoItem-linked** (``archiver_info_item_id`` provided): the InfoItem's existence
              is validated via the Archiver SDK (NotFound → 422); name defaults to the
              InfoItem's name when omitted.
            - **URL-only** (``url`` provided, no ``archiver_info_item_id``): the URL is probed
              for ``effective_url`` + ``domain_name``; name defaults to the probed
              domain. Produces a WatchedItem with ``archiver_info_item_id=None`` (#185 Phase A).

            At least one of ``archiver_info_item_id`` or ``url`` is required.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | WatchedItemResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
