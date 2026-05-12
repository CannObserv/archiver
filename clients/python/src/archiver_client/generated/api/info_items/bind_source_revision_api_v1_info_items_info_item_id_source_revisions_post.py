from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_source_revision_create import InfoItemSourceRevisionCreate
from ...models.info_item_source_revision_out import InfoItemSourceRevisionOut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemSourceRevisionCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/info-items/{info_item_id}/source-revisions".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | InfoItemSourceRevisionOut | None:
    if response.status_code == 201:
        response_201 = InfoItemSourceRevisionOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | InfoItemSourceRevisionOut]:
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
    body: InfoItemSourceRevisionCreate,
) -> Response[EnvelopeResponse | InfoItemSourceRevisionOut]:
    """Bind Source Revision

     Bind a SourceRevision to an InfoItem (idempotent).

    If a binding for (info_item_id, source_revision_id) already exists, it is
    returned unchanged. Returns 404 if the InfoItem or SourceRevision doesn't exist.

    Args:
        info_item_id (str):
        body (InfoItemSourceRevisionCreate): Request body for POST /info-items/{id}/source-
            revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceRevisionOut]
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
    body: InfoItemSourceRevisionCreate,
) -> EnvelopeResponse | InfoItemSourceRevisionOut | None:
    """Bind Source Revision

     Bind a SourceRevision to an InfoItem (idempotent).

    If a binding for (info_item_id, source_revision_id) already exists, it is
    returned unchanged. Returns 404 if the InfoItem or SourceRevision doesn't exist.

    Args:
        info_item_id (str):
        body (InfoItemSourceRevisionCreate): Request body for POST /info-items/{id}/source-
            revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceRevisionOut
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
    body: InfoItemSourceRevisionCreate,
) -> Response[EnvelopeResponse | InfoItemSourceRevisionOut]:
    """Bind Source Revision

     Bind a SourceRevision to an InfoItem (idempotent).

    If a binding for (info_item_id, source_revision_id) already exists, it is
    returned unchanged. Returns 404 if the InfoItem or SourceRevision doesn't exist.

    Args:
        info_item_id (str):
        body (InfoItemSourceRevisionCreate): Request body for POST /info-items/{id}/source-
            revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoItemSourceRevisionOut]
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
    body: InfoItemSourceRevisionCreate,
) -> EnvelopeResponse | InfoItemSourceRevisionOut | None:
    """Bind Source Revision

     Bind a SourceRevision to an InfoItem (idempotent).

    If a binding for (info_item_id, source_revision_id) already exists, it is
    returned unchanged. Returns 404 if the InfoItem or SourceRevision doesn't exist.

    Args:
        info_item_id (str):
        body (InfoItemSourceRevisionCreate): Request body for POST /info-items/{id}/source-
            revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoItemSourceRevisionOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
            body=body,
        )
    ).parsed
