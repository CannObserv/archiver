from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.validate_watch_spec_request import ValidateWatchSpecRequest
from ...models.validate_watch_spec_response import ValidateWatchSpecResponse
from ...types import Response


def _get_kwargs(
    *,
    body: ValidateWatchSpecRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/validate-watch-spec",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | ValidateWatchSpecResponse | None:
    if response.status_code == 200:
        response_200 = ValidateWatchSpecResponse.from_dict(response.json())

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
) -> Response[EnvelopeResponse | ValidateWatchSpecResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateWatchSpecRequest,
) -> Response[EnvelopeResponse | ValidateWatchSpecResponse]:
    """Validate Watch Spec Route

     Validate a WatchSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateWatchSpecRequest): Request body for POST /api/v1/tools/validate-watch-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ValidateWatchSpecResponse]
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
    body: ValidateWatchSpecRequest,
) -> EnvelopeResponse | ValidateWatchSpecResponse | None:
    """Validate Watch Spec Route

     Validate a WatchSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateWatchSpecRequest): Request body for POST /api/v1/tools/validate-watch-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ValidateWatchSpecResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateWatchSpecRequest,
) -> Response[EnvelopeResponse | ValidateWatchSpecResponse]:
    """Validate Watch Spec Route

     Validate a WatchSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateWatchSpecRequest): Request body for POST /api/v1/tools/validate-watch-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ValidateWatchSpecResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ValidateWatchSpecRequest,
) -> EnvelopeResponse | ValidateWatchSpecResponse | None:
    """Validate Watch Spec Route

     Validate a WatchSpec document against the v1 JSON Schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateWatchSpecRequest): Request body for POST /api/v1/tools/validate-watch-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ValidateWatchSpecResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
