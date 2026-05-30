from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_source_out import InfoItemSourceOut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    info_source_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/v1/info-items/{info_item_id}/info-sources/{info_source_id}".format(
            info_item_id=quote(str(info_item_id), safe=""),
            info_source_id=quote(str(info_source_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | InfoItemSourceOut | None:
    if response.status_code == 200:
        response_200 = InfoItemSourceOut.from_dict(response.json())
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
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[EnvelopeResponse | InfoItemSourceOut]:
    """Deactivate Info Source Binding

     Deactivate an InfoItemSource binding (sets deactivated_at).

    Returns the deactivated binding row. 404 when no active binding exists.

    Args:
        info_item_id (str):
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> EnvelopeResponse | InfoItemSourceOut | None:
    """Deactivate Info Source Binding

     Deactivate an InfoItemSource binding (sets deactivated_at).

    Returns the deactivated binding row. 404 when no active binding exists.

    Args:
        info_item_id (str):
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceOut
    """

    return sync_detailed(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[EnvelopeResponse | InfoItemSourceOut]:
    """Deactivate Info Source Binding

     Deactivate an InfoItemSource binding (sets deactivated_at).

    Returns the deactivated binding row. 404 when no active binding exists.

    Args:
        info_item_id (str):
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> EnvelopeResponse | InfoItemSourceOut | None:
    """Deactivate Info Source Binding

     Deactivate an InfoItemSource binding (sets deactivated_at).

    Returns the deactivated binding row. 404 when no active binding exists.

    Args:
        info_item_id (str):
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            info_source_id=info_source_id,
            client=client,
        )
    ).parsed
