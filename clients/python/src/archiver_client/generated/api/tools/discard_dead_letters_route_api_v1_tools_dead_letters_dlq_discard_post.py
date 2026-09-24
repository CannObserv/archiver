from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.discard_dead_letters_request import DiscardDeadLettersRequest
from ...models.discard_dead_letters_response import DiscardDeadLettersResponse
from ...models.envelope_response import EnvelopeResponse
from ...types import Response


def _get_kwargs(
    dlq: str,
    *,
    body: DiscardDeadLettersRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/dead-letters/{dlq}/discard".format(
            dlq=quote(str(dlq), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DiscardDeadLettersResponse | EnvelopeResponse | None:
    if response.status_code == 200:
        response_200 = DiscardDeadLettersResponse.from_dict(response.json())

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
) -> Response[DiscardDeadLettersResponse | EnvelopeResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dlq: str,
    *,
    client: AuthenticatedClient,
    body: DiscardDeadLettersRequest,
) -> Response[DiscardDeadLettersResponse | EnvelopeResponse]:
    """Discard Dead Letters Route

     Delete the named entries from one of archiver's two DLQs (archiver#238).

    ``XDEL`` by id, each frame logged in full to journald first. Ids not in the
    queue come back in ``not_found`` rather than failing the request, so a
    retried discard is harmless.

    Args:
        dlq (str):
        body (DiscardDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DiscardDeadLettersResponse | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        dlq=dlq,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dlq: str,
    *,
    client: AuthenticatedClient,
    body: DiscardDeadLettersRequest,
) -> DiscardDeadLettersResponse | EnvelopeResponse | None:
    """Discard Dead Letters Route

     Delete the named entries from one of archiver's two DLQs (archiver#238).

    ``XDEL`` by id, each frame logged in full to journald first. Ids not in the
    queue come back in ``not_found`` rather than failing the request, so a
    retried discard is harmless.

    Args:
        dlq (str):
        body (DiscardDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DiscardDeadLettersResponse | EnvelopeResponse
    """

    return sync_detailed(
        dlq=dlq,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    dlq: str,
    *,
    client: AuthenticatedClient,
    body: DiscardDeadLettersRequest,
) -> Response[DiscardDeadLettersResponse | EnvelopeResponse]:
    """Discard Dead Letters Route

     Delete the named entries from one of archiver's two DLQs (archiver#238).

    ``XDEL`` by id, each frame logged in full to journald first. Ids not in the
    queue come back in ``not_found`` rather than failing the request, so a
    retried discard is harmless.

    Args:
        dlq (str):
        body (DiscardDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DiscardDeadLettersResponse | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        dlq=dlq,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dlq: str,
    *,
    client: AuthenticatedClient,
    body: DiscardDeadLettersRequest,
) -> DiscardDeadLettersResponse | EnvelopeResponse | None:
    """Discard Dead Letters Route

     Delete the named entries from one of archiver's two DLQs (archiver#238).

    ``XDEL`` by id, each frame logged in full to journald first. Ids not in the
    queue come back in ``not_found`` rather than failing the request, so a
    retried discard is harmless.

    Args:
        dlq (str):
        body (DiscardDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/discard.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DiscardDeadLettersResponse | EnvelopeResponse
    """

    return (
        await asyncio_detailed(
            dlq=dlq,
            client=client,
            body=body,
        )
    ).parsed
