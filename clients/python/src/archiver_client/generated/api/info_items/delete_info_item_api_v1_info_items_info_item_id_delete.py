from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...types import Response


def _get_kwargs(
    info_item_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/v1/info-items/{info_item_id}".format(
            info_item_id=quote(str(info_item_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | EnvelopeResponse | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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
) -> Response[Any | EnvelopeResponse]:
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
) -> Response[Any | EnvelopeResponse]:
    r"""Delete Info Item

     Delete an InfoItem. The registry's only exit for one (archiver#141).

    Exists so that leaving the registry has a **transactional home**. Once the
    announcement producer lands, ``revoked: true`` is the announced form of \"gone
    from the registry\", and it must be written to ``changes_outbox`` in the same
    transaction as the deletion. Raw SQL cannot do that: a psql ``DELETE`` skips
    the tombstone, and every consumer keeps the key forever. The periodic full
    republish does **not** repair it — ``revoked`` is an explicit tombstone
    precisely because absence-from-a-full-set is not the delete signal here.

    The alternative considered was declaring InfoItems undeletable and saying so
    in ``docs/SCHEMA.md``. Rejected: it does not stop anyone reaching for psql,
    and the failure it leaves behind is silent and permanent.

    **Cascade scope.** The item's bindings and rep-spec assignments go with it —
    both FKs are ``ondelete=\"CASCADE\"``. The InfoSource and its SourceRevisions do
    not: an InfoSource can be the active primary for several InfoItems, and
    ``source_revisions`` keys on ``info_source_id``, so its ``RESTRICT`` never
    sees an item delete.

    404 on an already-deleted item rather than a silent 204 — an operator who
    deletes the wrong ULID twice should learn the second call did nothing.

    **Known gap: nothing is confirmed to consume the tombstone.** The revocation
    is announced on ``info.registry`` — that is the designed channel, and there is
    no HTTP push left to add — but watcher#254 (the reconcile loop) does not
    mention tombstone handling, so a deleted InfoItem's WatchedItem may need
    removing in Watcher by hand until that is verified. See ``docs/SCHEMA.md``.

    Args:
        info_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | EnvelopeResponse | None:
    r"""Delete Info Item

     Delete an InfoItem. The registry's only exit for one (archiver#141).

    Exists so that leaving the registry has a **transactional home**. Once the
    announcement producer lands, ``revoked: true`` is the announced form of \"gone
    from the registry\", and it must be written to ``changes_outbox`` in the same
    transaction as the deletion. Raw SQL cannot do that: a psql ``DELETE`` skips
    the tombstone, and every consumer keeps the key forever. The periodic full
    republish does **not** repair it — ``revoked`` is an explicit tombstone
    precisely because absence-from-a-full-set is not the delete signal here.

    The alternative considered was declaring InfoItems undeletable and saying so
    in ``docs/SCHEMA.md``. Rejected: it does not stop anyone reaching for psql,
    and the failure it leaves behind is silent and permanent.

    **Cascade scope.** The item's bindings and rep-spec assignments go with it —
    both FKs are ``ondelete=\"CASCADE\"``. The InfoSource and its SourceRevisions do
    not: an InfoSource can be the active primary for several InfoItems, and
    ``source_revisions`` keys on ``info_source_id``, so its ``RESTRICT`` never
    sees an item delete.

    404 on an already-deleted item rather than a silent 204 — an operator who
    deletes the wrong ULID twice should learn the second call did nothing.

    **Known gap: nothing is confirmed to consume the tombstone.** The revocation
    is announced on ``info.registry`` — that is the designed channel, and there is
    no HTTP push left to add — but watcher#254 (the reconcile loop) does not
    mention tombstone handling, so a deleted InfoItem's WatchedItem may need
    removing in Watcher by hand until that is verified. See ``docs/SCHEMA.md``.

    Args:
        info_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvelopeResponse
    """

    return sync_detailed(
        info_item_id=info_item_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | EnvelopeResponse]:
    r"""Delete Info Item

     Delete an InfoItem. The registry's only exit for one (archiver#141).

    Exists so that leaving the registry has a **transactional home**. Once the
    announcement producer lands, ``revoked: true`` is the announced form of \"gone
    from the registry\", and it must be written to ``changes_outbox`` in the same
    transaction as the deletion. Raw SQL cannot do that: a psql ``DELETE`` skips
    the tombstone, and every consumer keeps the key forever. The periodic full
    republish does **not** repair it — ``revoked`` is an explicit tombstone
    precisely because absence-from-a-full-set is not the delete signal here.

    The alternative considered was declaring InfoItems undeletable and saying so
    in ``docs/SCHEMA.md``. Rejected: it does not stop anyone reaching for psql,
    and the failure it leaves behind is silent and permanent.

    **Cascade scope.** The item's bindings and rep-spec assignments go with it —
    both FKs are ``ondelete=\"CASCADE\"``. The InfoSource and its SourceRevisions do
    not: an InfoSource can be the active primary for several InfoItems, and
    ``source_revisions`` keys on ``info_source_id``, so its ``RESTRICT`` never
    sees an item delete.

    404 on an already-deleted item rather than a silent 204 — an operator who
    deletes the wrong ULID twice should learn the second call did nothing.

    **Known gap: nothing is confirmed to consume the tombstone.** The revocation
    is announced on ``info.registry`` — that is the designed channel, and there is
    no HTTP push left to add — but watcher#254 (the reconcile loop) does not
    mention tombstone handling, so a deleted InfoItem's WatchedItem may need
    removing in Watcher by hand until that is verified. See ``docs/SCHEMA.md``.

    Args:
        info_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | EnvelopeResponse | None:
    r"""Delete Info Item

     Delete an InfoItem. The registry's only exit for one (archiver#141).

    Exists so that leaving the registry has a **transactional home**. Once the
    announcement producer lands, ``revoked: true`` is the announced form of \"gone
    from the registry\", and it must be written to ``changes_outbox`` in the same
    transaction as the deletion. Raw SQL cannot do that: a psql ``DELETE`` skips
    the tombstone, and every consumer keeps the key forever. The periodic full
    republish does **not** repair it — ``revoked`` is an explicit tombstone
    precisely because absence-from-a-full-set is not the delete signal here.

    The alternative considered was declaring InfoItems undeletable and saying so
    in ``docs/SCHEMA.md``. Rejected: it does not stop anyone reaching for psql,
    and the failure it leaves behind is silent and permanent.

    **Cascade scope.** The item's bindings and rep-spec assignments go with it —
    both FKs are ``ondelete=\"CASCADE\"``. The InfoSource and its SourceRevisions do
    not: an InfoSource can be the active primary for several InfoItems, and
    ``source_revisions`` keys on ``info_source_id``, so its ``RESTRICT`` never
    sees an item delete.

    404 on an already-deleted item rather than a silent 204 — an operator who
    deletes the wrong ULID twice should learn the second call did nothing.

    **Known gap: nothing is confirmed to consume the tombstone.** The revocation
    is announced on ``info.registry`` — that is the designed channel, and there is
    no HTTP push left to add — but watcher#254 (the reconcile loop) does not
    mention tombstone handling, so a deleted InfoItem's WatchedItem may need
    removing in Watcher by hand until that is verified. See ``docs/SCHEMA.md``.

    Args:
        info_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvelopeResponse
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            client=client,
        )
    ).parsed
