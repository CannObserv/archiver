from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.change_revision_response import ChangeRevisionResponse
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    watched_item_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/watched-items/{watched_item_id}/revisions".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[ChangeRevisionResponse] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = ChangeRevisionResponse.from_dict(response_200_item_data)

            response_200.append(response_200_item)

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
) -> Response[HTTPValidationError | list[ChangeRevisionResponse]]:
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
) -> Response[HTTPValidationError | list[ChangeRevisionResponse]]:
    """List Revisions

     List ChangeRevisions for a WatchedItem, newest first.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[ChangeRevisionResponse]]
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
) -> HTTPValidationError | list[ChangeRevisionResponse] | None:
    """List Revisions

     List ChangeRevisions for a WatchedItem, newest first.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[ChangeRevisionResponse]
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | list[ChangeRevisionResponse]]:
    """List Revisions

     List ChangeRevisions for a WatchedItem, newest first.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[ChangeRevisionResponse]]
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
) -> HTTPValidationError | list[ChangeRevisionResponse] | None:
    """List Revisions

     List ChangeRevisions for a WatchedItem, newest first.

    Args:
        watched_item_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[ChangeRevisionResponse]
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            client=client,
        )
    ).parsed
