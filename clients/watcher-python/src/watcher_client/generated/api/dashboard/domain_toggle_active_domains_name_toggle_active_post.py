from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_domain_toggle_active_domains_name_toggle_active_post import (
    BodyDomainToggleActiveDomainsNameToggleActivePost,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    *,
    body: BodyDomainToggleActiveDomainsNameToggleActivePost | Unset = UNSET,
    q: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
    sort: str | Unset = "name",
    order: str | Unset = "asc",
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    json_q: None | str | Unset
    if isinstance(q, Unset):
        json_q = UNSET
    else:
        json_q = q
    params["q"] = json_q

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    else:
        json_status = status
    params["status"] = json_status

    params["sort"] = sort

    params["order"] = order

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/domains/{name}/toggle-active".format(
            name=quote(str(name), safe=""),
        ),
        "params": params,
    }

    if not isinstance(body, Unset):
        _kwargs["data"] = body.to_dict()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    _kwargs["headers"] = headers
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
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyDomainToggleActiveDomainsNameToggleActivePost | Unset = UNSET,
    q: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
    sort: str | Unset = "name",
    order: str | Unset = "asc",
) -> Response[Any | HTTPValidationError]:
    """Domain Toggle Active

     Toggle domain active status.

    Deactivating suspends every WatchedItem on the domain (``domain_suspended``);
    reactivating clears the flag. ``domain_suspended`` gates scheduling and the
    pause/resume toggle directly — the WatchedItem is the single monitored entity.

    Args:
        name (str):
        q (None | str | Unset):
        status (None | str | Unset):
        sort (str | Unset):  Default: 'name'.
        order (str | Unset):  Default: 'asc'.
        body (BodyDomainToggleActiveDomainsNameToggleActivePost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
        q=q,
        status=status,
        sort=sort,
        order=order,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyDomainToggleActiveDomainsNameToggleActivePost | Unset = UNSET,
    q: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
    sort: str | Unset = "name",
    order: str | Unset = "asc",
) -> Any | HTTPValidationError | None:
    """Domain Toggle Active

     Toggle domain active status.

    Deactivating suspends every WatchedItem on the domain (``domain_suspended``);
    reactivating clears the flag. ``domain_suspended`` gates scheduling and the
    pause/resume toggle directly — the WatchedItem is the single monitored entity.

    Args:
        name (str):
        q (None | str | Unset):
        status (None | str | Unset):
        sort (str | Unset):  Default: 'name'.
        order (str | Unset):  Default: 'asc'.
        body (BodyDomainToggleActiveDomainsNameToggleActivePost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        name=name,
        client=client,
        body=body,
        q=q,
        status=status,
        sort=sort,
        order=order,
    ).parsed


async def asyncio_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyDomainToggleActiveDomainsNameToggleActivePost | Unset = UNSET,
    q: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
    sort: str | Unset = "name",
    order: str | Unset = "asc",
) -> Response[Any | HTTPValidationError]:
    """Domain Toggle Active

     Toggle domain active status.

    Deactivating suspends every WatchedItem on the domain (``domain_suspended``);
    reactivating clears the flag. ``domain_suspended`` gates scheduling and the
    pause/resume toggle directly — the WatchedItem is the single monitored entity.

    Args:
        name (str):
        q (None | str | Unset):
        status (None | str | Unset):
        sort (str | Unset):  Default: 'name'.
        order (str | Unset):  Default: 'asc'.
        body (BodyDomainToggleActiveDomainsNameToggleActivePost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
        q=q,
        status=status,
        sort=sort,
        order=order,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: BodyDomainToggleActiveDomainsNameToggleActivePost | Unset = UNSET,
    q: None | str | Unset = UNSET,
    status: None | str | Unset = UNSET,
    sort: str | Unset = "name",
    order: str | Unset = "asc",
) -> Any | HTTPValidationError | None:
    """Domain Toggle Active

     Toggle domain active status.

    Deactivating suspends every WatchedItem on the domain (``domain_suspended``);
    reactivating clears the flag. ``domain_suspended`` gates scheduling and the
    pause/resume toggle directly — the WatchedItem is the single monitored entity.

    Args:
        name (str):
        q (None | str | Unset):
        status (None | str | Unset):
        sort (str | Unset):  Default: 'name'.
        order (str | Unset):  Default: 'asc'.
        body (BodyDomainToggleActiveDomainsNameToggleActivePost | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            name=name,
            client=client,
            body=body,
            q=q,
            status=status,
            sort=sort,
            order=order,
        )
    ).parsed
