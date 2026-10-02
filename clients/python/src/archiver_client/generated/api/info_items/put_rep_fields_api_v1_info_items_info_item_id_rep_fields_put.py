from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_out import InfoItemOut
from ...models.info_item_rep_fields_put import InfoItemRepFieldsPut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemRepFieldsPut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/rep-fields".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | InfoItemOut | None:
    if response.status_code == 200:
        response_200 = InfoItemOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | InfoItemOut]:
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
    body: InfoItemRepFieldsPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Rep Fields

     Replace an InfoItem's rep_fields bag (archiver#302).

    The only route that changes a bag after create. A whole-bag PUT like
    ``/watch-spec``: the bag is judged as a unit against every active
    assignment, which a merge would make a read-modify-write of state the
    caller never saw.

    Refusals leave the stored bag untouched:

    - **422** ``rep_fields_invalid``: not Rep Fields v1.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the bag
      would break an active assignment. ``data.refusals`` names every one.
    - **409** ``rep_fields_moves_destination``: valid, but an active
      assignment would render somewhere else from now on. ``data.moves``
      carries each path before and after; resend with
      ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: ``rep_fields`` rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemRepFieldsPut): Request body for PUT /info-items/{id}/rep-fields
            (archiver#302).

            Replaces the whole bag; this is not a merge. The bag must be v1-shaped and
            keep every active assignment able to render. A valid bag that changes where
            an active assignment renders is refused with 409 unless
            ``allow_destination_change`` is true: later occasions would land at the new
            path, beside everything already published at the old one.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemOut]
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
    body: InfoItemRepFieldsPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Rep Fields

     Replace an InfoItem's rep_fields bag (archiver#302).

    The only route that changes a bag after create. A whole-bag PUT like
    ``/watch-spec``: the bag is judged as a unit against every active
    assignment, which a merge would make a read-modify-write of state the
    caller never saw.

    Refusals leave the stored bag untouched:

    - **422** ``rep_fields_invalid``: not Rep Fields v1.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the bag
      would break an active assignment. ``data.refusals`` names every one.
    - **409** ``rep_fields_moves_destination``: valid, but an active
      assignment would render somewhere else from now on. ``data.moves``
      carries each path before and after; resend with
      ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: ``rep_fields`` rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemRepFieldsPut): Request body for PUT /info-items/{id}/rep-fields
            (archiver#302).

            Replaces the whole bag; this is not a merge. The bag must be v1-shaped and
            keep every active assignment able to render. A valid bag that changes where
            an active assignment renders is refused with 409 unless
            ``allow_destination_change`` is true: later occasions would land at the new
            path, beside everything already published at the old one.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemOut
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
    body: InfoItemRepFieldsPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Rep Fields

     Replace an InfoItem's rep_fields bag (archiver#302).

    The only route that changes a bag after create. A whole-bag PUT like
    ``/watch-spec``: the bag is judged as a unit against every active
    assignment, which a merge would make a read-modify-write of state the
    caller never saw.

    Refusals leave the stored bag untouched:

    - **422** ``rep_fields_invalid``: not Rep Fields v1.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the bag
      would break an active assignment. ``data.refusals`` names every one.
    - **409** ``rep_fields_moves_destination``: valid, but an active
      assignment would render somewhere else from now on. ``data.moves``
      carries each path before and after; resend with
      ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: ``rep_fields`` rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemRepFieldsPut): Request body for PUT /info-items/{id}/rep-fields
            (archiver#302).

            Replaces the whole bag; this is not a merge. The bag must be v1-shaped and
            keep every active assignment able to render. A valid bag that changes where
            an active assignment renders is refused with 409 unless
            ``allow_destination_change`` is true: later occasions would land at the new
            path, beside everything already published at the old one.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemOut]
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
    body: InfoItemRepFieldsPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Rep Fields

     Replace an InfoItem's rep_fields bag (archiver#302).

    The only route that changes a bag after create. A whole-bag PUT like
    ``/watch-spec``: the bag is judged as a unit against every active
    assignment, which a merge would make a read-modify-write of state the
    caller never saw.

    Refusals leave the stored bag untouched:

    - **422** ``rep_fields_invalid``: not Rep Fields v1.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the bag
      would break an active assignment. ``data.refusals`` names every one.
    - **409** ``rep_fields_moves_destination``: valid, but an active
      assignment would render somewhere else from now on. ``data.moves``
      carries each path before and after; resend with
      ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: ``rep_fields`` rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemRepFieldsPut): Request body for PUT /info-items/{id}/rep-fields
            (archiver#302).

            Replaces the whole bag; this is not a merge. The bag must be v1-shaped and
            keep every active assignment able to render. A valid bag that changes where
            an active assignment renders is refused with 409 unless
            ``allow_destination_change`` is true: later occasions would land at the new
            path, beside everything already published at the old one.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
            body=body,
        )
    ).parsed
