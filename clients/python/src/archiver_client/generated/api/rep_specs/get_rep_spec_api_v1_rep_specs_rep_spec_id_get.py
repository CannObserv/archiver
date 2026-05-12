from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
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
) -> EnvelopeResponse | RepSpecOut | None:
    if response.status_code == 200:
        response_200 = RepSpecOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | RepSpecOut]:
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
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
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
) -> EnvelopeResponse | RepSpecOut | None:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepSpecOut
    """

    return sync_detailed(
        rep_spec_id=rep_spec_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
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
) -> EnvelopeResponse | RepSpecOut | None:
    """Get Rep Spec

     Fetch a single RepSpec by ID.

    Args:
        rep_spec_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepSpecOut
    """

    return (
        await asyncio_detailed(
            rep_spec_id=rep_spec_id,
            client=client,
        )
    ).parsed
