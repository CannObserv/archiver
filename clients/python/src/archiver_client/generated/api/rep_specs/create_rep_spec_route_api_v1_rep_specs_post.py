from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
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
) -> EnvelopeResponse | RepSpecOut | None:
    if response.status_code == 201:
        response_201 = RepSpecOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | RepSpecOut]:
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
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
    ``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
    issues.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
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
) -> EnvelopeResponse | RepSpecOut | None:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
    ``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
    issues.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepSpecOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: RepSpecCreate,
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
    ``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
    issues.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
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
) -> EnvelopeResponse | RepSpecOut | None:
    """Create Rep Spec Route

     Author a new RepSpec.

    ``schema_version`` is server-defaulted to 1. The ``document`` field is
    validated against the v1 envelope and the matching per-provider
    sub-schema. ``body.provider`` and ``document['provider']`` must agree.

    Errors use the standard envelope (see ``src/api/errors.py``); ``kind`` is
    ``schema`` for envelope/sub-schema validation, ``body`` for Pydantic-level
    issues.

    Args:
        body (RepSpecCreate): Request body for POST /rep-specs.

            ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
            accepting a client-supplied value would be ceremony. Bump the server
            default (and add a discriminator) once a v2 envelope ships.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepSpecOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
