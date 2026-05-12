from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.validate_rep_fields_request import ValidateRepFieldsRequest
from ...models.validate_rep_fields_response import ValidateRepFieldsResponse
from ...types import Response


def _get_kwargs(
    *,
    body: ValidateRepFieldsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/validate-rep-fields",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | ValidateRepFieldsResponse | None:
    if response.status_code == 200:
        response_200 = ValidateRepFieldsResponse.from_dict(response.json())

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
) -> Response[EnvelopeResponse | ValidateRepFieldsResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRepFieldsRequest,
) -> Response[EnvelopeResponse | ValidateRepFieldsResponse]:
    """Validate Rep Fields Route

     Validate a rep_fields bag against the v1 schema and optional required_fields list.

    When ``required_fields`` is supplied, also checks that every 'ns.key' path
    resolves to a non-null value in the bag. Always returns 200 — validation is
    the purpose.

    Args:
        body (ValidateRepFieldsRequest): Request body for POST /api/v1/tools/validate-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ValidateRepFieldsResponse]
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
    body: ValidateRepFieldsRequest,
) -> EnvelopeResponse | ValidateRepFieldsResponse | None:
    """Validate Rep Fields Route

     Validate a rep_fields bag against the v1 schema and optional required_fields list.

    When ``required_fields`` is supplied, also checks that every 'ns.key' path
    resolves to a non-null value in the bag. Always returns 200 — validation is
    the purpose.

    Args:
        body (ValidateRepFieldsRequest): Request body for POST /api/v1/tools/validate-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ValidateRepFieldsResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRepFieldsRequest,
) -> Response[EnvelopeResponse | ValidateRepFieldsResponse]:
    """Validate Rep Fields Route

     Validate a rep_fields bag against the v1 schema and optional required_fields list.

    When ``required_fields`` is supplied, also checks that every 'ns.key' path
    resolves to a non-null value in the bag. Always returns 200 — validation is
    the purpose.

    Args:
        body (ValidateRepFieldsRequest): Request body for POST /api/v1/tools/validate-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ValidateRepFieldsResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ValidateRepFieldsRequest,
) -> EnvelopeResponse | ValidateRepFieldsResponse | None:
    """Validate Rep Fields Route

     Validate a rep_fields bag against the v1 schema and optional required_fields list.

    When ``required_fields`` is supplied, also checks that every 'ns.key' path
    resolves to a non-null value in the bag. Always returns 200 — validation is
    the purpose.

    Args:
        body (ValidateRepFieldsRequest): Request body for POST /api/v1/tools/validate-rep-fields.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ValidateRepFieldsResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
