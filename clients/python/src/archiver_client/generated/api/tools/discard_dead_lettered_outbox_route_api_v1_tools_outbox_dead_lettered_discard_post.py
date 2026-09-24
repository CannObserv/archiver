from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.discard_outbox_rows_request import DiscardOutboxRowsRequest
from ...models.discard_outbox_rows_response import DiscardOutboxRowsResponse
from ...models.envelope_response import EnvelopeResponse
from ...types import Response


def _get_kwargs(
    *,
    body: DiscardOutboxRowsRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/outbox/dead-lettered/discard",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DiscardOutboxRowsResponse | EnvelopeResponse | None:
    if response.status_code == 200:
        response_200 = DiscardOutboxRowsResponse.from_dict(response.json())

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
) -> Response[DiscardOutboxRowsResponse | EnvelopeResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: DiscardOutboxRowsRequest,
) -> Response[DiscardOutboxRowsResponse | EnvelopeResponse]:
    """Discard Dead Lettered Outbox Route

     Delete the named dead-lettered outbox rows (archiver#191).

    Each row is logged in full to journald first. One transaction, so a failure
    deletes nothing. An id that is not a dead-lettered row comes back in
    ``not_found`` - a live or published row is never touched - so a retried
    discard is harmless.

    Args:
        body (DiscardOutboxRowsRequest): Request body for POST /api/v1/tools/outbox/dead-
            lettered/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DiscardOutboxRowsResponse | EnvelopeResponse]
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
    body: DiscardOutboxRowsRequest,
) -> DiscardOutboxRowsResponse | EnvelopeResponse | None:
    """Discard Dead Lettered Outbox Route

     Delete the named dead-lettered outbox rows (archiver#191).

    Each row is logged in full to journald first. One transaction, so a failure
    deletes nothing. An id that is not a dead-lettered row comes back in
    ``not_found`` - a live or published row is never touched - so a retried
    discard is harmless.

    Args:
        body (DiscardOutboxRowsRequest): Request body for POST /api/v1/tools/outbox/dead-
            lettered/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DiscardOutboxRowsResponse | EnvelopeResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: DiscardOutboxRowsRequest,
) -> Response[DiscardOutboxRowsResponse | EnvelopeResponse]:
    """Discard Dead Lettered Outbox Route

     Delete the named dead-lettered outbox rows (archiver#191).

    Each row is logged in full to journald first. One transaction, so a failure
    deletes nothing. An id that is not a dead-lettered row comes back in
    ``not_found`` - a live or published row is never touched - so a retried
    discard is harmless.

    Args:
        body (DiscardOutboxRowsRequest): Request body for POST /api/v1/tools/outbox/dead-
            lettered/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DiscardOutboxRowsResponse | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: DiscardOutboxRowsRequest,
) -> DiscardOutboxRowsResponse | EnvelopeResponse | None:
    """Discard Dead Lettered Outbox Route

     Delete the named dead-lettered outbox rows (archiver#191).

    Each row is logged in full to journald first. One transaction, so a failure
    deletes nothing. An id that is not a dead-lettered row comes back in
    ``not_found`` - a live or published row is never touched - so a retried
    discard is harmless.

    Args:
        body (DiscardOutboxRowsRequest): Request body for POST /api/v1/tools/outbox/dead-
            lettered/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DiscardOutboxRowsResponse | EnvelopeResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
