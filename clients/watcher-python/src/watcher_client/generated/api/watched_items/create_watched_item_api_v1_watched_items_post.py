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

     Create a WatchedItem for an Archiver InfoItem.

    One path since #251: ``archiver_info_item_id``, ``url`` and
    ``archiver_info_source_id`` are all required (schema-enforced). The InfoItem
    is validated via the Archiver SDK and the name defaults to the InfoItem's
    name. Errors: NotFound → 422, AuthError → 500, ServerError/network → 503,
    duplicate InfoItem → 409.

    **Both ids must be canonical ULIDs — uppercase Crockford base32.** That is
    what ``ULID.from_str`` accepts, so it is what path parameters have always
    required and what ``ULIDRefStr`` now enforces here; the OpenAPI document
    advertises the same pattern. Archiver's provisioning call satisfies this by
    construction (``str()`` of a ``ULID``); a caller that lowercases its ids
    gets a 422 naming the field.

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            One creation path (#251): every WatchedItem is an Archiver InfoItem being
            watched. ``archiver_info_item_id`` is validated via the Archiver SDK
            (NotFound → 422) and the name defaults to the InfoItem's name when omitted;
            ``url`` is the InfoSource URL Archiver is authoritative for (stored as
            ``effective_url``, never re-probed); ``archiver_info_source_id`` identifies
            the InfoSource that observed revisions are posted back to. All three are
            required — the URL-only path was rolled back with bare-URL WatchedItems.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

            ``content_media_type`` is normally auto-detected from the first successful
            fetch (#168); supplying it here pre-seeds an operator override.

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

     Create a WatchedItem for an Archiver InfoItem.

    One path since #251: ``archiver_info_item_id``, ``url`` and
    ``archiver_info_source_id`` are all required (schema-enforced). The InfoItem
    is validated via the Archiver SDK and the name defaults to the InfoItem's
    name. Errors: NotFound → 422, AuthError → 500, ServerError/network → 503,
    duplicate InfoItem → 409.

    **Both ids must be canonical ULIDs — uppercase Crockford base32.** That is
    what ``ULID.from_str`` accepts, so it is what path parameters have always
    required and what ``ULIDRefStr`` now enforces here; the OpenAPI document
    advertises the same pattern. Archiver's provisioning call satisfies this by
    construction (``str()`` of a ``ULID``); a caller that lowercases its ids
    gets a 422 naming the field.

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            One creation path (#251): every WatchedItem is an Archiver InfoItem being
            watched. ``archiver_info_item_id`` is validated via the Archiver SDK
            (NotFound → 422) and the name defaults to the InfoItem's name when omitted;
            ``url`` is the InfoSource URL Archiver is authoritative for (stored as
            ``effective_url``, never re-probed); ``archiver_info_source_id`` identifies
            the InfoSource that observed revisions are posted back to. All three are
            required — the URL-only path was rolled back with bare-URL WatchedItems.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

            ``content_media_type`` is normally auto-detected from the first successful
            fetch (#168); supplying it here pre-seeds an operator override.

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

     Create a WatchedItem for an Archiver InfoItem.

    One path since #251: ``archiver_info_item_id``, ``url`` and
    ``archiver_info_source_id`` are all required (schema-enforced). The InfoItem
    is validated via the Archiver SDK and the name defaults to the InfoItem's
    name. Errors: NotFound → 422, AuthError → 500, ServerError/network → 503,
    duplicate InfoItem → 409.

    **Both ids must be canonical ULIDs — uppercase Crockford base32.** That is
    what ``ULID.from_str`` accepts, so it is what path parameters have always
    required and what ``ULIDRefStr`` now enforces here; the OpenAPI document
    advertises the same pattern. Archiver's provisioning call satisfies this by
    construction (``str()`` of a ``ULID``); a caller that lowercases its ids
    gets a 422 naming the field.

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            One creation path (#251): every WatchedItem is an Archiver InfoItem being
            watched. ``archiver_info_item_id`` is validated via the Archiver SDK
            (NotFound → 422) and the name defaults to the InfoItem's name when omitted;
            ``url`` is the InfoSource URL Archiver is authoritative for (stored as
            ``effective_url``, never re-probed); ``archiver_info_source_id`` identifies
            the InfoSource that observed revisions are posted back to. All three are
            required — the URL-only path was rolled back with bare-URL WatchedItems.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

            ``content_media_type`` is normally auto-detected from the first successful
            fetch (#168); supplying it here pre-seeds an operator override.

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

     Create a WatchedItem for an Archiver InfoItem.

    One path since #251: ``archiver_info_item_id``, ``url`` and
    ``archiver_info_source_id`` are all required (schema-enforced). The InfoItem
    is validated via the Archiver SDK and the name defaults to the InfoItem's
    name. Errors: NotFound → 422, AuthError → 500, ServerError/network → 503,
    duplicate InfoItem → 409.

    **Both ids must be canonical ULIDs — uppercase Crockford base32.** That is
    what ``ULID.from_str`` accepts, so it is what path parameters have always
    required and what ``ULIDRefStr`` now enforces here; the OpenAPI document
    advertises the same pattern. Archiver's provisioning call satisfies this by
    construction (``str()`` of a ``ULID``); a caller that lowercases its ids
    gets a 422 naming the field.

    Args:
        body (WatchedItemCreate): Create a WatchedItem via ``POST /api/v1/watched-items``.

            One creation path (#251): every WatchedItem is an Archiver InfoItem being
            watched. ``archiver_info_item_id`` is validated via the Archiver SDK
            (NotFound → 422) and the name defaults to the InfoItem's name when omitted;
            ``url`` is the InfoSource URL Archiver is authoritative for (stored as
            ``effective_url``, never re-probed); ``archiver_info_source_id`` identifies
            the InfoSource that observed revisions are posted back to. All three are
            required — the URL-only path was rolled back with bare-URL WatchedItems.

            ``source_specs`` seeds the local pipeline extraction config. Optional at
            create time; updatable later via PATCH.

            ``content_media_type`` is normally auto-detected from the first successful
            fetch (#168); supplying it here pre-seeds an operator override.

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
