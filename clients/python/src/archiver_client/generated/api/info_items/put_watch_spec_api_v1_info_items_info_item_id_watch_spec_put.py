from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_item_out import InfoItemOut
from ...models.info_item_watch_spec_put import InfoItemWatchSpecPut
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    *,
    body: InfoItemWatchSpecPut,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/api/v1/info-items/{info_item_id}/watch-spec".format(
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
    body: InfoItemWatchSpecPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    r"""Put Watch Spec

     Replace an InfoItem's cadence policy.

    A whole-document PUT rather than a general InfoItem PATCH: the document is
    validated as a unit, and omitting ``interval`` is the only way to express
    \"the consumer applies its own default\" — a merge would make that state
    unreachable once an interval had been set.

    Cadence only. Pause state is ``PUT /watch-active``, which keeps this body to
    one absence rule and keeps pausing from becoming a read-modify-write of a
    document the operator did not mean to touch.

    The stored document is left untouched when validation fails — including for
    a pre-rework client that still nests ``active``, which the schema rejects
    rather than silently dropping.

    Args:
        info_item_id (str):
        body (InfoItemWatchSpecPut): Request body for PUT /info-items/{id}/watch-spec.

            Replaces the whole document — this is not a merge. Omitting ``interval`` is
            how "the consumer applies its own default" is expressed, so a merge would
            make that state unreachable once an interval had been set.

            Carries cadence only. Pause state has its own route (``PUT /watch-active``)
            precisely so this body keeps one absence rule instead of two.

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
    body: InfoItemWatchSpecPut,
) -> EnvelopeResponse | InfoItemOut | None:
    r"""Put Watch Spec

     Replace an InfoItem's cadence policy.

    A whole-document PUT rather than a general InfoItem PATCH: the document is
    validated as a unit, and omitting ``interval`` is the only way to express
    \"the consumer applies its own default\" — a merge would make that state
    unreachable once an interval had been set.

    Cadence only. Pause state is ``PUT /watch-active``, which keeps this body to
    one absence rule and keeps pausing from becoming a read-modify-write of a
    document the operator did not mean to touch.

    The stored document is left untouched when validation fails — including for
    a pre-rework client that still nests ``active``, which the schema rejects
    rather than silently dropping.

    Args:
        info_item_id (str):
        body (InfoItemWatchSpecPut): Request body for PUT /info-items/{id}/watch-spec.

            Replaces the whole document — this is not a merge. Omitting ``interval`` is
            how "the consumer applies its own default" is expressed, so a merge would
            make that state unreachable once an interval had been set.

            Carries cadence only. Pause state has its own route (``PUT /watch-active``)
            precisely so this body keeps one absence rule instead of two.

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
    body: InfoItemWatchSpecPut,
) -> Response[EnvelopeResponse | InfoItemOut]:
    r"""Put Watch Spec

     Replace an InfoItem's cadence policy.

    A whole-document PUT rather than a general InfoItem PATCH: the document is
    validated as a unit, and omitting ``interval`` is the only way to express
    \"the consumer applies its own default\" — a merge would make that state
    unreachable once an interval had been set.

    Cadence only. Pause state is ``PUT /watch-active``, which keeps this body to
    one absence rule and keeps pausing from becoming a read-modify-write of a
    document the operator did not mean to touch.

    The stored document is left untouched when validation fails — including for
    a pre-rework client that still nests ``active``, which the schema rejects
    rather than silently dropping.

    Args:
        info_item_id (str):
        body (InfoItemWatchSpecPut): Request body for PUT /info-items/{id}/watch-spec.

            Replaces the whole document — this is not a merge. Omitting ``interval`` is
            how "the consumer applies its own default" is expressed, so a merge would
            make that state unreachable once an interval had been set.

            Carries cadence only. Pause state has its own route (``PUT /watch-active``)
            precisely so this body keeps one absence rule instead of two.

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
    body: InfoItemWatchSpecPut,
) -> EnvelopeResponse | InfoItemOut | None:
    r"""Put Watch Spec

     Replace an InfoItem's cadence policy.

    A whole-document PUT rather than a general InfoItem PATCH: the document is
    validated as a unit, and omitting ``interval`` is the only way to express
    \"the consumer applies its own default\" — a merge would make that state
    unreachable once an interval had been set.

    Cadence only. Pause state is ``PUT /watch-active``, which keeps this body to
    one absence rule and keeps pausing from becoming a read-modify-write of a
    document the operator did not mean to touch.

    The stored document is left untouched when validation fails — including for
    a pre-rework client that still nests ``active``, which the schema rejects
    rather than silently dropping.

    Args:
        info_item_id (str):
        body (InfoItemWatchSpecPut): Request body for PUT /info-items/{id}/watch-spec.

            Replaces the whole document — this is not a merge. Omitting ``interval`` is
            how "the consumer applies its own default" is expressed, so a merge would
            make that state unreachable once an interval had been set.

            Carries cadence only. Pause state has its own route (``PUT /watch-active``)
            precisely so this body keeps one absence rule instead of two.

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
