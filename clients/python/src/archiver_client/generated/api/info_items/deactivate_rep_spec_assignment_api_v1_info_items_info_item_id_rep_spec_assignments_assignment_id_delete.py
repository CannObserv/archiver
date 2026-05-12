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
    assignment_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/api/v1/info-items/{info_item_id}/rep-spec-assignments/{assignment_id}".format(
            info_item_id=quote(str(info_item_id), safe=""),
            assignment_id=quote(str(assignment_id), safe=""),
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
    assignment_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | EnvelopeResponse]:
    """Deactivate Rep Spec Assignment

     Deactivate a RepSpec assignment by setting ``deactivated_at = now()``.

    Returns 204 on success. Returns 404 if the assignment doesn't exist or
    does not belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | EnvelopeResponse | None:
    """Deactivate Rep Spec Assignment

     Deactivate a RepSpec assignment by setting ``deactivated_at = now()``.

    Returns 204 on success. Returns 404 if the assignment doesn't exist or
    does not belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvelopeResponse
    """

    return sync_detailed(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | EnvelopeResponse]:
    """Deactivate Rep Spec Assignment

     Deactivate a RepSpec assignment by setting ``deactivated_at = now()``.

    Returns 204 on success. Returns 404 if the assignment doesn't exist or
    does not belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | EnvelopeResponse]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
) -> Any | EnvelopeResponse | None:
    """Deactivate Rep Spec Assignment

     Deactivate a RepSpec assignment by setting ``deactivated_at = now()``.

    Returns 204 on success. Returns 404 if the assignment doesn't exist or
    does not belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | EnvelopeResponse
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            assignment_id=assignment_id,
            client=client,
        )
    ).parsed
