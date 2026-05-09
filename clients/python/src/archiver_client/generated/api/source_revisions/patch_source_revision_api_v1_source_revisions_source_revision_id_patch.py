from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.source_revision_cache_patch import SourceRevisionCachePatch
from ...models.source_revision_out import SourceRevisionOut
from ...types import Response


def _get_kwargs(
    source_revision_id: str,
    *,
    body: SourceRevisionCachePatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/source-revisions/{source_revision_id}".format(
            source_revision_id=quote(str(source_revision_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SourceRevisionOut | None:
    if response.status_code == 200:
        response_200 = SourceRevisionOut.from_dict(response.json())

        return response_200

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
    source_revision_id: str,
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCachePatch,
) -> Response[HTTPValidationError | SourceRevisionOut]:
    """Patch Source Revision

     Partially update cache fields on an existing SourceRevision.

    Only fields present in the request body are applied; omitted fields are
    left untouched.  Sending ``null`` explicitly clears the field.

    Raises:
        404: ``source_revision_id`` does not reference a known SourceRevision.
        422: ``source_revision_id`` is not a valid ULID.

    Args:
        source_revision_id (str):
        body (SourceRevisionCachePatch): Request body for PATCH /source-revisions/{id}.

            Both fields are optional (omitting leaves the DB column untouched).
            Supplying ``null`` explicitly clears the field.
            Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SourceRevisionOut]
    """

    kwargs = _get_kwargs(
        source_revision_id=source_revision_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    source_revision_id: str,
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCachePatch,
) -> HTTPValidationError | SourceRevisionOut | None:
    """Patch Source Revision

     Partially update cache fields on an existing SourceRevision.

    Only fields present in the request body are applied; omitted fields are
    left untouched.  Sending ``null`` explicitly clears the field.

    Raises:
        404: ``source_revision_id`` does not reference a known SourceRevision.
        422: ``source_revision_id`` is not a valid ULID.

    Args:
        source_revision_id (str):
        body (SourceRevisionCachePatch): Request body for PATCH /source-revisions/{id}.

            Both fields are optional (omitting leaves the DB column untouched).
            Supplying ``null`` explicitly clears the field.
            Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SourceRevisionOut
    """

    return sync_detailed(
        source_revision_id=source_revision_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    source_revision_id: str,
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCachePatch,
) -> Response[HTTPValidationError | SourceRevisionOut]:
    """Patch Source Revision

     Partially update cache fields on an existing SourceRevision.

    Only fields present in the request body are applied; omitted fields are
    left untouched.  Sending ``null`` explicitly clears the field.

    Raises:
        404: ``source_revision_id`` does not reference a known SourceRevision.
        422: ``source_revision_id`` is not a valid ULID.

    Args:
        source_revision_id (str):
        body (SourceRevisionCachePatch): Request body for PATCH /source-revisions/{id}.

            Both fields are optional (omitting leaves the DB column untouched).
            Supplying ``null`` explicitly clears the field.
            Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SourceRevisionOut]
    """

    kwargs = _get_kwargs(
        source_revision_id=source_revision_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    source_revision_id: str,
    *,
    client: AuthenticatedClient,
    body: SourceRevisionCachePatch,
) -> HTTPValidationError | SourceRevisionOut | None:
    """Patch Source Revision

     Partially update cache fields on an existing SourceRevision.

    Only fields present in the request body are applied; omitted fields are
    left untouched.  Sending ``null`` explicitly clears the field.

    Raises:
        404: ``source_revision_id`` does not reference a known SourceRevision.
        422: ``source_revision_id`` is not a valid ULID.

    Args:
        source_revision_id (str):
        body (SourceRevisionCachePatch): Request body for PATCH /source-revisions/{id}.

            Both fields are optional (omitting leaves the DB column untouched).
            Supplying ``null`` explicitly clears the field.
            Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SourceRevisionOut
    """

    return (
        await asyncio_detailed(
            source_revision_id=source_revision_id,
            client=client,
            body=body,
        )
    ).parsed
