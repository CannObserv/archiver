from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.rep_spec_out import RepSpecOut
from ...types import Response


def _get_kwargs(
    rep_spec_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/rep-specs/{rep_spec_id}".format(
            rep_spec_id=quote(str(rep_spec_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | RepSpecOut | None:
    if response.status_code == 200:
        response_200 = RepSpecOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | RepSpecOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | RepSpecOut]:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RepSpecOut]
    """

    kwargs = _get_kwargs(
        rep_spec_id=rep_spec_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | RepSpecOut | None:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RepSpecOut
    """

    return sync_detailed(
        rep_spec_id=rep_spec_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[HTTPValidationError | RepSpecOut]:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RepSpecOut]
    """

    kwargs = _get_kwargs(
        rep_spec_id=rep_spec_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
) -> HTTPValidationError | RepSpecOut | None:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RepSpecOut
    """

    return (
        await asyncio_detailed(
            rep_spec_id=rep_spec_id,
            client=client,
        )
    ).parsed
