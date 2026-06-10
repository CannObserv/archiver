from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.domain_field_partial_domains_name_field_field_name_get_mode import (
    DomainFieldPartialDomainsNameFieldFieldNameGetMode,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    field_name: str,
    *,
    mode: DomainFieldPartialDomainsNameFieldFieldNameGetMode
    | Unset = DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_mode: str | Unset = UNSET
    if not isinstance(mode, Unset):
        json_mode = mode.value

    params["mode"] = json_mode

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/domains/{name}/field/{field_name}".format(
            name=quote(str(name), safe=""),
            field_name=quote(str(field_name), safe=""),
        ),
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
    name: str,
    field_name: str,
    *,
    client: AuthenticatedClient | Client,
    mode: DomainFieldPartialDomainsNameFieldFieldNameGetMode
    | Unset = DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW,
) -> Response[Any | HTTPValidationError]:
    """Domain Field Partial

     Serve a single domain field partial in view or edit mode.

    Args:
        name (str):
        field_name (str):
        mode (DomainFieldPartialDomainsNameFieldFieldNameGetMode | Unset):  Default:
            DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        field_name=field_name,
        mode=mode,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    field_name: str,
    *,
    client: AuthenticatedClient | Client,
    mode: DomainFieldPartialDomainsNameFieldFieldNameGetMode
    | Unset = DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW,
) -> Any | HTTPValidationError | None:
    """Domain Field Partial

     Serve a single domain field partial in view or edit mode.

    Args:
        name (str):
        field_name (str):
        mode (DomainFieldPartialDomainsNameFieldFieldNameGetMode | Unset):  Default:
            DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        name=name,
        field_name=field_name,
        client=client,
        mode=mode,
    ).parsed


async def asyncio_detailed(
    name: str,
    field_name: str,
    *,
    client: AuthenticatedClient | Client,
    mode: DomainFieldPartialDomainsNameFieldFieldNameGetMode
    | Unset = DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW,
) -> Response[Any | HTTPValidationError]:
    """Domain Field Partial

     Serve a single domain field partial in view or edit mode.

    Args:
        name (str):
        field_name (str):
        mode (DomainFieldPartialDomainsNameFieldFieldNameGetMode | Unset):  Default:
            DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        name=name,
        field_name=field_name,
        mode=mode,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    field_name: str,
    *,
    client: AuthenticatedClient | Client,
    mode: DomainFieldPartialDomainsNameFieldFieldNameGetMode
    | Unset = DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW,
) -> Any | HTTPValidationError | None:
    """Domain Field Partial

     Serve a single domain field partial in view or edit mode.

    Args:
        name (str):
        field_name (str):
        mode (DomainFieldPartialDomainsNameFieldFieldNameGetMode | Unset):  Default:
            DomainFieldPartialDomainsNameFieldFieldNameGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            name=name,
            field_name=field_name,
            client=client,
            mode=mode,
        )
    ).parsed
