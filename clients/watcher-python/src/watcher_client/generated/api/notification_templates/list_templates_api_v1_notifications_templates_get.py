from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.notification_template_response import NotificationTemplateResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    visibility: None | str | Unset = UNSET,
    domain_name: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_visibility: None | str | Unset
    if isinstance(visibility, Unset):
        json_visibility = UNSET
    else:
        json_visibility = visibility
    params["visibility"] = json_visibility

    json_domain_name: None | str | Unset
    if isinstance(domain_name, Unset):
        json_domain_name = UNSET
    else:
        json_domain_name = domain_name
    params["domain_name"] = json_domain_name

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/notifications/templates",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | list[NotificationTemplateResponse] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = NotificationTemplateResponse.from_dict(response_200_item_data)

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
) -> Response[HTTPValidationError | list[NotificationTemplateResponse]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    visibility: None | str | Unset = UNSET,
    domain_name: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | list[NotificationTemplateResponse]]:
    """List Templates

     List notification templates, optionally filtered by visibility/domain.

    Args:
        visibility (None | str | Unset):
        domain_name (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[NotificationTemplateResponse]]
    """

    kwargs = _get_kwargs(
        visibility=visibility,
        domain_name=domain_name,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    visibility: None | str | Unset = UNSET,
    domain_name: None | str | Unset = UNSET,
) -> HTTPValidationError | list[NotificationTemplateResponse] | None:
    """List Templates

     List notification templates, optionally filtered by visibility/domain.

    Args:
        visibility (None | str | Unset):
        domain_name (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[NotificationTemplateResponse]
    """

    return sync_detailed(
        client=client,
        visibility=visibility,
        domain_name=domain_name,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    visibility: None | str | Unset = UNSET,
    domain_name: None | str | Unset = UNSET,
) -> Response[HTTPValidationError | list[NotificationTemplateResponse]]:
    """List Templates

     List notification templates, optionally filtered by visibility/domain.

    Args:
        visibility (None | str | Unset):
        domain_name (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[NotificationTemplateResponse]]
    """

    kwargs = _get_kwargs(
        visibility=visibility,
        domain_name=domain_name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    visibility: None | str | Unset = UNSET,
    domain_name: None | str | Unset = UNSET,
) -> HTTPValidationError | list[NotificationTemplateResponse] | None:
    """List Templates

     List notification templates, optionally filtered by visibility/domain.

    Args:
        visibility (None | str | Unset):
        domain_name (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[NotificationTemplateResponse]
    """

    return (
        await asyncio_detailed(
            client=client,
            visibility=visibility,
            domain_name=domain_name,
        )
    ).parsed
