from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.republish_registry_response import RepublishRegistryResponse
from ...types import Response


def _get_kwargs() -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/republish-registry-announcements",
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | RepublishRegistryResponse | None:
    if response.status_code == 202:
        response_202 = RepublishRegistryResponse.from_dict(response.json())

        return response_202

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
) -> Response[EnvelopeResponse | RepublishRegistryResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[EnvelopeResponse | RepublishRegistryResponse]:
    r"""Republish Registry Announcements Route

     Trigger an immediate full-set republish on ``info.registry`` (archiver#141).

    The operator's \"republish now\": sets the event the snapshot loop waits on,
    so the publish happens on the loop's task — 202, never blocking an HTTP
    worker on a full-set publish. 409 when the bus is dormant (no
    ``ARCHIVER_REDIS_URL``, e.g. the dev server): a silent 202 that never
    publishes would read as success.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepublishRegistryResponse]
    """

    kwargs = _get_kwargs()

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
) -> EnvelopeResponse | RepublishRegistryResponse | None:
    r"""Republish Registry Announcements Route

     Trigger an immediate full-set republish on ``info.registry`` (archiver#141).

    The operator's \"republish now\": sets the event the snapshot loop waits on,
    so the publish happens on the loop's task — 202, never blocking an HTTP
    worker on a full-set publish. 409 when the bus is dormant (no
    ``ARCHIVER_REDIS_URL``, e.g. the dev server): a silent 202 that never
    publishes would read as success.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepublishRegistryResponse
    """

    return sync_detailed(
        client=client,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
) -> Response[EnvelopeResponse | RepublishRegistryResponse]:
    r"""Republish Registry Announcements Route

     Trigger an immediate full-set republish on ``info.registry`` (archiver#141).

    The operator's \"republish now\": sets the event the snapshot loop waits on,
    so the publish happens on the loop's task — 202, never blocking an HTTP
    worker on a full-set publish. 409 when the bus is dormant (no
    ``ARCHIVER_REDIS_URL``, e.g. the dev server): a silent 202 that never
    publishes would read as success.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepublishRegistryResponse]
    """

    kwargs = _get_kwargs()

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
) -> EnvelopeResponse | RepublishRegistryResponse | None:
    r"""Republish Registry Announcements Route

     Trigger an immediate full-set republish on ``info.registry`` (archiver#141).

    The operator's \"republish now\": sets the event the snapshot loop waits on,
    so the publish happens on the loop's task — 202, never blocking an HTTP
    worker on a full-set publish. 409 when the bus is dormant (no
    ``ARCHIVER_REDIS_URL``, e.g. the dev server): a silent 202 that never
    publishes would read as success.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepublishRegistryResponse
    """

    return (
        await asyncio_detailed(
            client=client,
        )
    ).parsed
