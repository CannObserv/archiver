from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    event_type: None | str | Unset = UNSET,
    watch_id: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_event_type: None | str | Unset
    if isinstance(event_type, Unset):
        json_event_type = UNSET
    else:
        json_event_type = event_type
    params["event_type"] = json_event_type

    json_watch_id: None | str | Unset
    if isinstance(watch_id, Unset):
        json_watch_id = UNSET
    else:
        json_watch_id = watch_id
    params["watch_id"] = json_watch_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/audit",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = response.json()
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
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    event_type: None | str | Unset = UNSET,
    watch_id: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Audit Log Page

     Audit log page with filtering.

    Args:
        event_type (None | str | Unset):
        watch_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        event_type=event_type,
        watch_id=watch_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    event_type: None | str | Unset = UNSET,
    watch_id: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Audit Log Page

     Audit log page with filtering.

    Args:
        event_type (None | str | Unset):
        watch_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        event_type=event_type,
        watch_id=watch_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    event_type: None | str | Unset = UNSET,
    watch_id: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Audit Log Page

     Audit log page with filtering.

    Args:
        event_type (None | str | Unset):
        watch_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        event_type=event_type,
        watch_id=watch_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    event_type: None | str | Unset = UNSET,
    watch_id: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Audit Log Page

     Audit log page with filtering.

    Args:
        event_type (None | str | Unset):
        watch_id (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            event_type=event_type,
            watch_id=watch_id,
        )
    ).parsed
