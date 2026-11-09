from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_out import InfoItemOut
from ...models.info_item_tags_put import InfoItemTagsPut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemTagsPut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/tags".format(
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
    body: InfoItemTagsPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Tags

     Replace an InfoItem's tags (archiver#362).

    The whole set, so ``[]`` clears it and two writers race to last-writer-wins,
    by design; the dashboard's add and remove lock instead. A tag breaking the
    rule (``info_item_tags.normalize_tags``) is a 422 naming each by its path,
    and nothing is stored. Allowed on an archived item: archive is watch-only.
    Announces nothing - tags never go on the bus.

    Args:
        info_item_id (str):
        body (InfoItemTagsPut): Request body for PUT /info-items/{id}/tags (archiver#362).

            The whole set, replacing what is stored: ``[]`` clears it. ``tags`` is
            required, so clearing is said, never implied by an omitted field.

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
    body: InfoItemTagsPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Tags

     Replace an InfoItem's tags (archiver#362).

    The whole set, so ``[]`` clears it and two writers race to last-writer-wins,
    by design; the dashboard's add and remove lock instead. A tag breaking the
    rule (``info_item_tags.normalize_tags``) is a 422 naming each by its path,
    and nothing is stored. Allowed on an archived item: archive is watch-only.
    Announces nothing - tags never go on the bus.

    Args:
        info_item_id (str):
        body (InfoItemTagsPut): Request body for PUT /info-items/{id}/tags (archiver#362).

            The whole set, replacing what is stored: ``[]`` clears it. ``tags`` is
            required, so clearing is said, never implied by an omitted field.

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
    body: InfoItemTagsPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    """Put Tags

     Replace an InfoItem's tags (archiver#362).

    The whole set, so ``[]`` clears it and two writers race to last-writer-wins,
    by design; the dashboard's add and remove lock instead. A tag breaking the
    rule (``info_item_tags.normalize_tags``) is a 422 naming each by its path,
    and nothing is stored. Allowed on an archived item: archive is watch-only.
    Announces nothing - tags never go on the bus.

    Args:
        info_item_id (str):
        body (InfoItemTagsPut): Request body for PUT /info-items/{id}/tags (archiver#362).

            The whole set, replacing what is stored: ``[]`` clears it. ``tags`` is
            required, so clearing is said, never implied by an omitted field.

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
    body: InfoItemTagsPut,
) -> EnvelopeResponse | InfoItemOut | None:
    """Put Tags

     Replace an InfoItem's tags (archiver#362).

    The whole set, so ``[]`` clears it and two writers race to last-writer-wins,
    by design; the dashboard's add and remove lock instead. A tag breaking the
    rule (``info_item_tags.normalize_tags``) is a 422 naming each by its path,
    and nothing is stored. Allowed on an archived item: archive is watch-only.
    Announces nothing - tags never go on the bus.

    Args:
        info_item_id (str):
        body (InfoItemTagsPut): Request body for PUT /info-items/{id}/tags (archiver#362).

            The whole set, replacing what is stored: ``[]`` clears it. ``tags`` is
            required, so clearing is said, never implied by an omitted field.

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
