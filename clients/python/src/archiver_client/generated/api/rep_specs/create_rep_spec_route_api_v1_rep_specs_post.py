from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.rep_spec_create import RepSpecCreate
from ...models.rep_spec_out import RepSpecOut
from ...types import Response


def _get_kwargs(
    *,
    body: RepSpecCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/rep-specs",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | RepSpecOut | None:
    if response.status_code == 201:
        response_201 = RepSpecOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | RepSpecOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: RepSpecCreate,
) -> Response[HTTPValidationError | RepSpecOut]:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Error responses:
    - 422: document fails envelope or provider sub-schema validation, or the
           request-level ``provider`` disagrees with ``document.provider``.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RepSpecOut]
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
    body: RepSpecCreate,
) -> HTTPValidationError | RepSpecOut | None:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Error responses:
    - 422: document fails envelope or provider sub-schema validation, or the
           request-level ``provider`` disagrees with ``document.provider``.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RepSpecOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: RepSpecCreate,
) -> Response[HTTPValidationError | RepSpecOut]:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Error responses:
    - 422: document fails envelope or provider sub-schema validation, or the
           request-level ``provider`` disagrees with ``document.provider``.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RepSpecOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: RepSpecCreate,
) -> HTTPValidationError | RepSpecOut | None:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Error responses:
    - 422: document fails envelope or provider sub-schema validation, or the
           request-level ``provider`` disagrees with ``document.provider``.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RepSpecOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
