from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
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
) -> HTTPValidationError | SourceRevisionOut | None:
    if response.status_code == 201:
        response_201 = SourceRevisionOut.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | SourceRevisionOut]:
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
) -> Response[HTTPValidationError | SourceRevisionOut]:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SourceRevisionOut]
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
) -> HTTPValidationError | SourceRevisionOut | None:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SourceRevisionOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCreate,
) -> Response[HTTPValidationError | SourceRevisionOut]:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SourceRevisionOut]
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
) -> HTTPValidationError | SourceRevisionOut | None:
    """Create Source Revision

     Create or return an existing SourceRevision.

    Idempotent on ``(info_source_id, content_fingerprint)``. Returns **201**
    on insert; **200** when the exact pair already exists.

    Raises:
        404: ``info_source_id`` does not reference a known InfoSource.
        422: ``content_fingerprint`` fails regex validation (Pydantic layer).

    Args:
        body (SourceRevisionCreate): Request body for POST /source-revisions.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SourceRevisionOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
