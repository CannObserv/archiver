from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.source_revision_create import SourceRevisionCreate
from ...models.source_revision_out import SourceRevisionOut
from ...types import Response


def _get_kwargs(
    *,
    body: SourceRevisionCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/source-revisions",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | SourceRevisionOut | None:
    if response.status_code == 201:
        response_201 = SourceRevisionOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | SourceRevisionOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCreate,
) -> Response[EnvelopeResponse | SourceRevisionOut]:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

            ``source_revision_id`` is optional and may be supplied by the client
            (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
            written under its final filename BEFORE the POST round-trips. When
            omitted, the server allocates a ULID. Idempotency on
            ``(info_source_id, content_fingerprint)`` still wins on re-POST —
            a client-supplied ULID is honored on fresh inserts only; existing
            rows are returned as-is.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | SourceRevisionOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCreate,
) -> EnvelopeResponse | SourceRevisionOut | None:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

            ``source_revision_id`` is optional and may be supplied by the client
            (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
            written under its final filename BEFORE the POST round-trips. When
            omitted, the server allocates a ULID. Idempotency on
            ``(info_source_id, content_fingerprint)`` still wins on re-POST —
            a client-supplied ULID is honored on fresh inserts only; existing
            rows are returned as-is.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | SourceRevisionOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCreate,
) -> Response[EnvelopeResponse | SourceRevisionOut]:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

            ``source_revision_id`` is optional and may be supplied by the client
            (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
            written under its final filename BEFORE the POST round-trips. When
            omitted, the server allocates a ULID. Idempotency on
            ``(info_source_id, content_fingerprint)`` still wins on re-POST —
            a client-supplied ULID is honored on fresh inserts only; existing
            rows are returned as-is.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | SourceRevisionOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCreate,
) -> EnvelopeResponse | SourceRevisionOut | None:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

            ``source_revision_id`` is optional and may be supplied by the client
            (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
            written under its final filename BEFORE the POST round-trips. When
            omitted, the server allocates a ULID. Idempotency on
            ``(info_source_id, content_fingerprint)`` still wins on re-POST —
            a client-supplied ULID is honored on fresh inserts only; existing
            rows are returned as-is.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | SourceRevisionOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
