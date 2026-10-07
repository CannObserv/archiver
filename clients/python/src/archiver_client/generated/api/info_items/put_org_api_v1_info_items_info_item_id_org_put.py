from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_org_put import InfoItemOrgPut
from ...models.info_item_out import InfoItemOut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemOrgPut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/org".format(
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
    body: InfoItemOrgPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Org

     Link an InfoItem to a Power Map org, or unlink it with ``null`` (archiver#304).

    Linking fetches the org from Power Map now and snapshots it locally; the
    effective bag's ``org.title``/``org.acronym`` come from that snapshot, so
    any stored copies are dropped. Unlinking writes the org's values back into
    the bag, so no path moves. A merged id links the org it was merged into.

    - **503**: Power Map not configured or unreachable; nothing is linked.
      ``data.reason`` says which; a 429 upstream carries ``Retry-After``.
    - **422** ``pm_org_not_found`` / ``pm_org_unnamed``: Power Map has no such
      org, or it has no canonical name to supply ``org.title``.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the new
      effective bag would break an active assignment; ``data.refusals``.
    - **409** ``rep_fields_moves_destination``: an active assignment would
      render somewhere else; ``data.moves`` has each path before and after.
      Resend with ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: org identity rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemOrgPut): Request body for PUT /info-items/{id}/org (archiver#304).

            ``pm_org_id`` is required, ``null`` included: unlinking is said, never
            implied by an omitted field.

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
    body: InfoItemOrgPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Org

     Link an InfoItem to a Power Map org, or unlink it with ``null`` (archiver#304).

    Linking fetches the org from Power Map now and snapshots it locally; the
    effective bag's ``org.title``/``org.acronym`` come from that snapshot, so
    any stored copies are dropped. Unlinking writes the org's values back into
    the bag, so no path moves. A merged id links the org it was merged into.

    - **503**: Power Map not configured or unreachable; nothing is linked.
      ``data.reason`` says which; a 429 upstream carries ``Retry-After``.
    - **422** ``pm_org_not_found`` / ``pm_org_unnamed``: Power Map has no such
      org, or it has no canonical name to supply ``org.title``.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the new
      effective bag would break an active assignment; ``data.refusals``.
    - **409** ``rep_fields_moves_destination``: an active assignment would
      render somewhere else; ``data.moves`` has each path before and after.
      Resend with ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: org identity rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemOrgPut): Request body for PUT /info-items/{id}/org (archiver#304).

            ``pm_org_id`` is required, ``null`` included: unlinking is said, never
            implied by an omitted field.

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
    body: InfoItemOrgPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Org

     Link an InfoItem to a Power Map org, or unlink it with ``null`` (archiver#304).

    Linking fetches the org from Power Map now and snapshots it locally; the
    effective bag's ``org.title``/``org.acronym`` come from that snapshot, so
    any stored copies are dropped. Unlinking writes the org's values back into
    the bag, so no path moves. A merged id links the org it was merged into.

    - **503**: Power Map not configured or unreachable; nothing is linked.
      ``data.reason`` says which; a 429 upstream carries ``Retry-After``.
    - **422** ``pm_org_not_found`` / ``pm_org_unnamed``: Power Map has no such
      org, or it has no canonical name to supply ``org.title``.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the new
      effective bag would break an active assignment; ``data.refusals``.
    - **409** ``rep_fields_moves_destination``: an active assignment would
      render somewhere else; ``data.moves`` has each path before and after.
      Resend with ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: org identity rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemOrgPut): Request body for PUT /info-items/{id}/org (archiver#304).

            ``pm_org_id`` is required, ``null`` included: unlinking is said, never
            implied by an omitted field.

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
    body: InfoItemOrgPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Org

     Link an InfoItem to a Power Map org, or unlink it with ``null`` (archiver#304).

    Linking fetches the org from Power Map now and snapshots it locally; the
    effective bag's ``org.title``/``org.acronym`` come from that snapshot, so
    any stored copies are dropped. Unlinking writes the org's values back into
    the bag, so no path moves. A merged id links the org it was merged into.

    - **503**: Power Map not configured or unreachable; nothing is linked.
      ``data.reason`` says which; a 429 upstream carries ``Retry-After``.
    - **422** ``pm_org_not_found`` / ``pm_org_unnamed``: Power Map has no such
      org, or it has no canonical name to supply ``org.title``.
    - **422** ``rep_fields_incomplete`` / ``rep_fields_unrenderable``: the new
      effective bag would break an active assignment; ``data.refusals``.
    - **409** ``rep_fields_moves_destination``: an active assignment would
      render somewhere else; ``data.moves`` has each path before and after.
      Resend with ``allow_destination_change: true`` to store it anyway.

    Nothing is announced: org identity rides no bus stream.

    Args:
        info_item_id (str):
        body (InfoItemOrgPut): Request body for PUT /info-items/{id}/org (archiver#304).

            ``pm_org_id`` is required, ``null`` included: unlinking is said, never
            implied by an omitted field.

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
