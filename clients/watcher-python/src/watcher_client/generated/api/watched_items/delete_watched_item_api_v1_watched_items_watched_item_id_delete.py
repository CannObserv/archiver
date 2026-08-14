from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/v1/watched-items/{watched_item_id}".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | HTTPValidationError]:
    """Delete Watched Item

     Permanently delete an archived WatchedItem (#210).

    Pre-flight: 404 if not found / malformed id; 409 if the item is not archived
    (archive first — archived already implies ``is_active=False``); **409 if the
    registry still announces it** (``applied_generation IS NOT NULL``, #254 CR-7).

    That last guard exists because deletion is no longer durable for a
    registry-owned item: ``info.registry`` is level-triggered, so the next
    announcement — or the hourly snapshot, carrying no change at all — simply
    recreates the row. Absence is not revocation; only a ``revoked: true``
    tombstone retires a key, and that is Archiver's call to make. A 409 naming
    the authority beats a delete that silently undoes itself within the snapshot
    period, and mirrors the 409 this route already returns for un-archived items.
    Rows the registry has no opinion on (``applied_generation IS NULL`` — created
    over this route and never announced) still delete, which is the whole
    population during the rollout. On success the
    DB cascades the item's children (``temporal_profiles``,
    ``notification_templates``, ``change_revisions``, ``pending_archiver_sync``)
    via their ``ON DELETE CASCADE`` FKs. An audit row is written before the delete
    and survives it (the WatchedItem id lives in the JSONB payload, not an FK).
    Archiver-side content (InfoItem / SourceRevisions) is left untouched.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | HTTPValidationError | None:
    """Delete Watched Item

     Permanently delete an archived WatchedItem (#210).

    Pre-flight: 404 if not found / malformed id; 409 if the item is not archived
    (archive first — archived already implies ``is_active=False``); **409 if the
    registry still announces it** (``applied_generation IS NOT NULL``, #254 CR-7).

    That last guard exists because deletion is no longer durable for a
    registry-owned item: ``info.registry`` is level-triggered, so the next
    announcement — or the hourly snapshot, carrying no change at all — simply
    recreates the row. Absence is not revocation; only a ``revoked: true``
    tombstone retires a key, and that is Archiver's call to make. A 409 naming
    the authority beats a delete that silently undoes itself within the snapshot
    period, and mirrors the 409 this route already returns for un-archived items.
    Rows the registry has no opinion on (``applied_generation IS NULL`` — created
    over this route and never announced) still delete, which is the whole
    population during the rollout. On success the
    DB cascades the item's children (``temporal_profiles``,
    ``notification_templates``, ``change_revisions``, ``pending_archiver_sync``)
    via their ``ON DELETE CASCADE`` FKs. An audit row is written before the delete
    and survives it (the WatchedItem id lives in the JSONB payload, not an FK).
    Archiver-side content (InfoItem / SourceRevisions) is left untouched.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | HTTPValidationError]:
    """Delete Watched Item

     Permanently delete an archived WatchedItem (#210).

    Pre-flight: 404 if not found / malformed id; 409 if the item is not archived
    (archive first — archived already implies ``is_active=False``); **409 if the
    registry still announces it** (``applied_generation IS NOT NULL``, #254 CR-7).

    That last guard exists because deletion is no longer durable for a
    registry-owned item: ``info.registry`` is level-triggered, so the next
    announcement — or the hourly snapshot, carrying no change at all — simply
    recreates the row. Absence is not revocation; only a ``revoked: true``
    tombstone retires a key, and that is Archiver's call to make. A 409 naming
    the authority beats a delete that silently undoes itself within the snapshot
    period, and mirrors the 409 this route already returns for un-archived items.
    Rows the registry has no opinion on (``applied_generation IS NULL`` — created
    over this route and never announced) still delete, which is the whole
    population during the rollout. On success the
    DB cascades the item's children (``temporal_profiles``,
    ``notification_templates``, ``change_revisions``, ``pending_archiver_sync``)
    via their ``ON DELETE CASCADE`` FKs. An audit row is written before the delete
    and survives it (the WatchedItem id lives in the JSONB payload, not an FK).
    Archiver-side content (InfoItem / SourceRevisions) is left untouched.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | HTTPValidationError | None:
    """Delete Watched Item

     Permanently delete an archived WatchedItem (#210).

    Pre-flight: 404 if not found / malformed id; 409 if the item is not archived
    (archive first — archived already implies ``is_active=False``); **409 if the
    registry still announces it** (``applied_generation IS NOT NULL``, #254 CR-7).

    That last guard exists because deletion is no longer durable for a
    registry-owned item: ``info.registry`` is level-triggered, so the next
    announcement — or the hourly snapshot, carrying no change at all — simply
    recreates the row. Absence is not revocation; only a ``revoked: true``
    tombstone retires a key, and that is Archiver's call to make. A 409 naming
    the authority beats a delete that silently undoes itself within the snapshot
    period, and mirrors the 409 this route already returns for un-archived items.
    Rows the registry has no opinion on (``applied_generation IS NULL`` — created
    over this route and never announced) still delete, which is the whole
    population during the rollout. On success the
    DB cascades the item's children (``temporal_profiles``,
    ``notification_templates``, ``change_revisions``, ``pending_archiver_sync``)
    via their ``ON DELETE CASCADE`` FKs. An audit row is written before the delete
    and survives it (the WatchedItem id lives in the JSONB payload, not an FK).
    Archiver-side content (InfoItem / SourceRevisions) is left untouched.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            client=client,
        )
    ).parsed
