from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.info_source_out import InfoSourceOut
from ...types import Response


def _get_kwargs(
    info_source_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/info-sources/{info_source_id}".format(
            info_source_id=quote(str(info_source_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InfoSourceOut | None:
    if response.status_code == 200:
        response_200 = InfoSourceOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | InfoSourceOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | InfoSourceOut]:
    """Get Info Source

     Fetch a single InfoSource by ID.

    Args:
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoSourceOut]
    """

    kwargs = _get_kwargs(
        info_source_id=info_source_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | InfoSourceOut | None:
    """Get Info Source

     Fetch a single InfoSource by ID.

    Args:
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoSourceOut
    """

    return sync_detailed(
        info_source_id=info_source_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | InfoSourceOut]:
    """Get Info Source

     Fetch a single InfoSource by ID.

    Args:
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoSourceOut]
    """

    kwargs = _get_kwargs(
        info_source_id=info_source_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | InfoSourceOut | None:
    """Get Info Source

     Fetch a single InfoSource by ID.

    Args:
        info_source_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoSourceOut
    """

    return (
        await asyncio_detailed(
            info_source_id=info_source_id,
            client=client,
        )
    ).parsed
