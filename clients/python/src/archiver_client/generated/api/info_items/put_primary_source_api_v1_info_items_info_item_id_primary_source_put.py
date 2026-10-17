from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_primary_source_put import InfoItemPrimarySourcePut
from ...models.info_item_source_out import InfoItemSourceOut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemPrimarySourcePut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/primary-source".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | InfoItemSourceOut | None:
    if response.status_code == 200:
        response_200 = InfoItemSourceOut.from_dict(response.json())

        return response_200

    if response.status_code == 201:
        response_201 = InfoItemSourceOut.from_dict(response.json())

        return response_201

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
) -> Response[EnvelopeResponse | InfoItemSourceOut]:
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
    body: InfoItemPrimarySourcePut,
) -> Response[EnvelopeResponse | InfoItemSourceOut]:
    """Put Primary Source

     Replace an InfoItem's primary InfoSource in one transaction (archiver#45).

    Deactivates the current primary, binds the new one, emits
    ``info_item_primary_changed`` and announces **once**, with the final state.
    This is the swap; ``DELETE …/info-sources/{id}`` then ``POST …/info-sources``
    is not one, because it announces revoked and then live.

    A source that was an earlier primary of this item starts a new tenure: a
    new binding row with its own ``id``; the earlier tenure keeps its
    ``created_at`` and ``deactivated_at`` (archiver#392).

    - **201**: the item had no active primary.
    - **200**: the primary was replaced, or was already this source (nothing
      written, nothing announced).
    - **404**: no such InfoItem or InfoSource.

    Args:
        info_item_id (str):
        body (InfoItemPrimarySourcePut): Request body for PUT /info-items/{id}/primary-source
            (archiver#45).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceOut]
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
    body: InfoItemPrimarySourcePut,
) -> EnvelopeResponse | InfoItemSourceOut | None:
    """Put Primary Source

     Replace an InfoItem's primary InfoSource in one transaction (archiver#45).

    Deactivates the current primary, binds the new one, emits
    ``info_item_primary_changed`` and announces **once**, with the final state.
    This is the swap; ``DELETE …/info-sources/{id}`` then ``POST …/info-sources``
    is not one, because it announces revoked and then live.

    A source that was an earlier primary of this item starts a new tenure: a
    new binding row with its own ``id``; the earlier tenure keeps its
    ``created_at`` and ``deactivated_at`` (archiver#392).

    - **201**: the item had no active primary.
    - **200**: the primary was replaced, or was already this source (nothing
      written, nothing announced).
    - **404**: no such InfoItem or InfoSource.

    Args:
        info_item_id (str):
        body (InfoItemPrimarySourcePut): Request body for PUT /info-items/{id}/primary-source
            (archiver#45).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceOut
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
    body: InfoItemPrimarySourcePut,
) -> Response[EnvelopeResponse | InfoItemSourceOut]:
    """Put Primary Source

     Replace an InfoItem's primary InfoSource in one transaction (archiver#45).

    Deactivates the current primary, binds the new one, emits
    ``info_item_primary_changed`` and announces **once**, with the final state.
    This is the swap; ``DELETE …/info-sources/{id}`` then ``POST …/info-sources``
    is not one, because it announces revoked and then live.

    A source that was an earlier primary of this item starts a new tenure: a
    new binding row with its own ``id``; the earlier tenure keeps its
    ``created_at`` and ``deactivated_at`` (archiver#392).

    - **201**: the item had no active primary.
    - **200**: the primary was replaced, or was already this source (nothing
      written, nothing announced).
    - **404**: no such InfoItem or InfoSource.

    Args:
        info_item_id (str):
        body (InfoItemPrimarySourcePut): Request body for PUT /info-items/{id}/primary-source
            (archiver#45).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceOut]
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
    body: InfoItemPrimarySourcePut,
) -> EnvelopeResponse | InfoItemSourceOut | None:
    """Put Primary Source

     Replace an InfoItem's primary InfoSource in one transaction (archiver#45).

    Deactivates the current primary, binds the new one, emits
    ``info_item_primary_changed`` and announces **once**, with the final state.
    This is the swap; ``DELETE …/info-sources/{id}`` then ``POST …/info-sources``
    is not one, because it announces revoked and then live.

    A source that was an earlier primary of this item starts a new tenure: a
    new binding row with its own ``id``; the earlier tenure keeps its
    ``created_at`` and ``deactivated_at`` (archiver#392).

    - **201**: the item had no active primary.
    - **200**: the primary was replaced, or was already this source (nothing
      written, nothing announced).
    - **404**: no such InfoItem or InfoSource.

    Args:
        info_item_id (str):
        body (InfoItemPrimarySourcePut): Request body for PUT /info-items/{id}/primary-source
            (archiver#45).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
            body=body,
        )
    ).parsed
