from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.page_dead_letter_out import PageDeadLetterOut
from ...types import UNSET, Response, Unset


def _get_kwargs(
    dlq: str,
    *,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/tools/dead-letters/{dlq}".format(
            dlq=quote(str(dlq), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | PageDeadLetterOut | None:
    if response.status_code == 200:
        response_200 = PageDeadLetterOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | PageDeadLetterOut]:
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
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageDeadLetterOut]:
    """List Dead Letters Route

     List one of archiver's two DLQs, oldest first, for triage (archiver#238).

    Each entry is tried against the running co-core, so ``decodes`` answers the
    version-skew question. 503 when the broker cannot be read, distinct from an
    empty page.

    Args:
        dlq (str):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageDeadLetterOut]
    """

    kwargs = _get_kwargs(
        dlq=dlq,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dlq: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageDeadLetterOut | None:
    """List Dead Letters Route

     List one of archiver's two DLQs, oldest first, for triage (archiver#238).

    Each entry is tried against the running co-core, so ``decodes`` answers the
    version-skew question. 503 when the broker cannot be read, distinct from an
    empty page.

    Args:
        dlq (str):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageDeadLetterOut
    """

    return sync_detailed(
        dlq=dlq,
        client=client,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    dlq: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[EnvelopeResponse | PageDeadLetterOut]:
    """List Dead Letters Route

     List one of archiver's two DLQs, oldest first, for triage (archiver#238).

    Each entry is tried against the running co-core, so ``decodes`` answers the
    version-skew question. 503 when the broker cannot be read, distinct from an
    empty page.

    Args:
        dlq (str):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | PageDeadLetterOut]
    """

    kwargs = _get_kwargs(
        dlq=dlq,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dlq: str,
    *,
    client: AuthenticatedClient,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> EnvelopeResponse | PageDeadLetterOut | None:
    """List Dead Letters Route

     List one of archiver's two DLQs, oldest first, for triage (archiver#238).

    Each entry is tried against the running co-core, so ``decodes`` answers the
    version-skew question. 503 when the broker cannot be read, distinct from an
    empty page.

    Args:
        dlq (str):
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | PageDeadLetterOut
    """

    return (
        await asyncio_detailed(
            dlq=dlq,
            client=client,
            limit=limit,
            offset=offset,
        )
    ).parsed
