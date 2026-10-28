from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.temporal_profile_out import TemporalProfileOut
from ...models.temporal_profile_put import TemporalProfilePut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: TemporalProfilePut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/temporal-profile".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | TemporalProfileOut | None:
    if response.status_code == 200:
        response_200 = TemporalProfileOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | TemporalProfileOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: TemporalProfilePut,
) -> Response[EnvelopeResponse | TemporalProfileOut]:
    """Put Temporal Profile

     Create or replace the item's temporal profile.

    Evaluated for today (UTC) on write: the response's ``resolved_interval`` is
    what the item now announces at the top of its cadence (profile, item,
    domain), and the write announces it when it moved. Every accepted write
    clears ``fired_at``, re-arming the post-action, so a profile whose window
    has already ended is refused with a 422. Stored but not announced on an
    item that cannot announce live (archiver#167).

    Args:
        info_item_id (str):
        body (TemporalProfilePut): Request body for PUT /info-items/{id}/temporal-profile: the
            whole profile.

            A create-or-replace, never a merge. ``event`` and ``deadline`` take a
            ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
            no ``reference_date``. Dates are UTC calendar days and absolute: nothing
            recurs yearly. A profile whose window has already ended is refused - every
            accepted write re-arms the post-action, which would then fire again.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | TemporalProfileOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: TemporalProfilePut,
) -> EnvelopeResponse | TemporalProfileOut | None:
    """Put Temporal Profile

     Create or replace the item's temporal profile.

    Evaluated for today (UTC) on write: the response's ``resolved_interval`` is
    what the item now announces at the top of its cadence (profile, item,
    domain), and the write announces it when it moved. Every accepted write
    clears ``fired_at``, re-arming the post-action, so a profile whose window
    has already ended is refused with a 422. Stored but not announced on an
    item that cannot announce live (archiver#167).

    Args:
        info_item_id (str):
        body (TemporalProfilePut): Request body for PUT /info-items/{id}/temporal-profile: the
            whole profile.

            A create-or-replace, never a merge. ``event`` and ``deadline`` take a
            ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
            no ``reference_date``. Dates are UTC calendar days and absolute: nothing
            recurs yearly. A profile whose window has already ended is refused - every
            accepted write re-arms the post-action, which would then fire again.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | TemporalProfileOut
    """

    return sync_detailed(
        info_item_id=info_item_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: TemporalProfilePut,
) -> Response[EnvelopeResponse | TemporalProfileOut]:
    """Put Temporal Profile

     Create or replace the item's temporal profile.

    Evaluated for today (UTC) on write: the response's ``resolved_interval`` is
    what the item now announces at the top of its cadence (profile, item,
    domain), and the write announces it when it moved. Every accepted write
    clears ``fired_at``, re-arming the post-action, so a profile whose window
    has already ended is refused with a 422. Stored but not announced on an
    item that cannot announce live (archiver#167).

    Args:
        info_item_id (str):
        body (TemporalProfilePut): Request body for PUT /info-items/{id}/temporal-profile: the
            whole profile.

            A create-or-replace, never a merge. ``event`` and ``deadline`` take a
            ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
            no ``reference_date``. Dates are UTC calendar days and absolute: nothing
            recurs yearly. A profile whose window has already ended is refused - every
            accepted write re-arms the post-action, which would then fire again.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | TemporalProfileOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
    body: TemporalProfilePut,
) -> EnvelopeResponse | TemporalProfileOut | None:
    """Put Temporal Profile

     Create or replace the item's temporal profile.

    Evaluated for today (UTC) on write: the response's ``resolved_interval`` is
    what the item now announces at the top of its cadence (profile, item,
    domain), and the write announces it when it moved. Every accepted write
    clears ``fired_at``, re-arming the post-action, so a profile whose window
    has already ended is refused with a 422. Stored but not announced on an
    item that cannot announce live (archiver#167).

    Args:
        info_item_id (str):
        body (TemporalProfilePut): Request body for PUT /info-items/{id}/temporal-profile: the
            whole profile.

            A create-or-replace, never a merge. ``event`` and ``deadline`` take a
            ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
            no ``reference_date``. Dates are UTC calendar days and absolute: nothing
            recurs yearly. A profile whose window has already ended is refused - every
            accepted write re-arms the post-action, which would then fire again.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | TemporalProfileOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
            body=body,
        )
    ).parsed
