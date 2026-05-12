from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.resolve_rep_fields_request import ResolveRepFieldsRequest
from ...models.resolve_rep_fields_response import ResolveRepFieldsResponse
from ...types import Response


def _get_kwargs(
    *,
    body: ResolveRepFieldsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/resolve-rep-fields",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | ResolveRepFieldsResponse | None:
    if response.status_code == 200:
        response_200 = ResolveRepFieldsResponse.from_dict(response.json())

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
) -> Response[EnvelopeResponse | ResolveRepFieldsResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ResolveRepFieldsRequest,
) -> Response[EnvelopeResponse | ResolveRepFieldsResponse]:
    """Resolve Rep Fields Route

     Enrich a raw rep_fields bag with slug companions and acronym_or_title derivations.

    Idempotent: existing ``_slug`` keys are preserved. Unknown namespaces and
    non-string values pass through unchanged.

    Args:
        body (ResolveRepFieldsRequest): Request body for POST /api/v1/tools/resolve-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ResolveRepFieldsResponse]
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
    body: ResolveRepFieldsRequest,
) -> EnvelopeResponse | ResolveRepFieldsResponse | None:
    """Resolve Rep Fields Route

     Enrich a raw rep_fields bag with slug companions and acronym_or_title derivations.

    Idempotent: existing ``_slug`` keys are preserved. Unknown namespaces and
    non-string values pass through unchanged.

    Args:
        body (ResolveRepFieldsRequest): Request body for POST /api/v1/tools/resolve-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ResolveRepFieldsResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ResolveRepFieldsRequest,
) -> Response[EnvelopeResponse | ResolveRepFieldsResponse]:
    """Resolve Rep Fields Route

     Enrich a raw rep_fields bag with slug companions and acronym_or_title derivations.

    Idempotent: existing ``_slug`` keys are preserved. Unknown namespaces and
    non-string values pass through unchanged.

    Args:
        body (ResolveRepFieldsRequest): Request body for POST /api/v1/tools/resolve-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ResolveRepFieldsResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ResolveRepFieldsRequest,
) -> EnvelopeResponse | ResolveRepFieldsResponse | None:
    """Resolve Rep Fields Route

     Enrich a raw rep_fields bag with slug companions and acronym_or_title derivations.

    Idempotent: existing ``_slug`` keys are preserved. Unknown namespaces and
    non-string values pass through unchanged.

    Args:
        body (ResolveRepFieldsRequest): Request body for POST /api/v1/tools/resolve-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ResolveRepFieldsResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
