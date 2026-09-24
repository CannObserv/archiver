from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.reprocess_dead_letters_request import ReprocessDeadLettersRequest
from ...models.reprocess_dead_letters_response import ReprocessDeadLettersResponse
from ...types import Response


def _get_kwargs(
    dlq: str,
    *,
    body: ReprocessDeadLettersRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/dead-letters/{dlq}/reprocess".format(
            dlq=quote(str(dlq), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | ReprocessDeadLettersResponse | None:
    if response.status_code == 200:
        response_200 = ReprocessDeadLettersResponse.from_dict(response.json())

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
) -> Response[EnvelopeResponse | ReprocessDeadLettersResponse]:
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
    body: ReprocessDeadLettersRequest,
) -> Response[EnvelopeResponse | ReprocessDeadLettersResponse]:
    """Reprocess Dead Letters Route

     Run the named entries through the queue's own handler (archiver#238).

    The handler is the one the consumer loop runs, so an entry is decided exactly
    as a live delivery would be; only a settled one is ``XDEL``ed, after its frame
    is logged. An entry another group parked, or one with no provenance, is left
    alone. Every outcome is per entry, in request order. A broker failure
    part-way through is a 503 whose ``data`` carries ``results`` so far and
    ``in_doubt`` (the id whose delete was in flight, its handler already
    committed; or null).

    Args:
        dlq (str): The dead-letter queue, by its key as broker names it: `content.revisions.dlq`
            or `content.artifacts.dlq`. Any other key is a 422.
        body (ReprocessDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/reprocess.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ReprocessDeadLettersResponse]
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
    body: ReprocessDeadLettersRequest,
) -> EnvelopeResponse | ReprocessDeadLettersResponse | None:
    """Reprocess Dead Letters Route

     Run the named entries through the queue's own handler (archiver#238).

    The handler is the one the consumer loop runs, so an entry is decided exactly
    as a live delivery would be; only a settled one is ``XDEL``ed, after its frame
    is logged. An entry another group parked, or one with no provenance, is left
    alone. Every outcome is per entry, in request order. A broker failure
    part-way through is a 503 whose ``data`` carries ``results`` so far and
    ``in_doubt`` (the id whose delete was in flight, its handler already
    committed; or null).

    Args:
        dlq (str): The dead-letter queue, by its key as broker names it: `content.revisions.dlq`
            or `content.artifacts.dlq`. Any other key is a 422.
        body (ReprocessDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/reprocess.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ReprocessDeadLettersResponse
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
    body: ReprocessDeadLettersRequest,
) -> Response[EnvelopeResponse | ReprocessDeadLettersResponse]:
    """Reprocess Dead Letters Route

     Run the named entries through the queue's own handler (archiver#238).

    The handler is the one the consumer loop runs, so an entry is decided exactly
    as a live delivery would be; only a settled one is ``XDEL``ed, after its frame
    is logged. An entry another group parked, or one with no provenance, is left
    alone. Every outcome is per entry, in request order. A broker failure
    part-way through is a 503 whose ``data`` carries ``results`` so far and
    ``in_doubt`` (the id whose delete was in flight, its handler already
    committed; or null).

    Args:
        dlq (str): The dead-letter queue, by its key as broker names it: `content.revisions.dlq`
            or `content.artifacts.dlq`. Any other key is a 422.
        body (ReprocessDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/reprocess.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | ReprocessDeadLettersResponse]
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
    body: ReprocessDeadLettersRequest,
) -> EnvelopeResponse | ReprocessDeadLettersResponse | None:
    """Reprocess Dead Letters Route

     Run the named entries through the queue's own handler (archiver#238).

    The handler is the one the consumer loop runs, so an entry is decided exactly
    as a live delivery would be; only a settled one is ``XDEL``ed, after its frame
    is logged. An entry another group parked, or one with no provenance, is left
    alone. Every outcome is per entry, in request order. A broker failure
    part-way through is a 503 whose ``data`` carries ``results`` so far and
    ``in_doubt`` (the id whose delete was in flight, its handler already
    committed; or null).

    Args:
        dlq (str): The dead-letter queue, by its key as broker names it: `content.revisions.dlq`
            or `content.artifacts.dlq`. Any other key is a 422.
        body (ReprocessDeadLettersRequest): Request body for POST /api/v1/tools/dead-
            letters/{dlq}/reprocess.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | ReprocessDeadLettersResponse
    """

    return (
        await asyncio_detailed(
            dlq=dlq,
            client=client,
            body=body,
        )
    ).parsed
