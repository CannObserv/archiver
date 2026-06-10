from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.notification_template_create import NotificationTemplateCreate
from ...models.notification_template_response import NotificationTemplateResponse
from ...types import Response


def _get_kwargs(
    *,
    body: NotificationTemplateCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/notifications/templates",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | NotificationTemplateResponse | None:
    if response.status_code == 201:
        response_201 = NotificationTemplateResponse.from_dict(response.json())

        return response_201

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateCreate,
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
    """Create Template

     Create a new shared notification template.

    Args:
        body (NotificationTemplateCreate): `str_strip_whitespace` runs before length validation,
            so a
            whitespace-only `channel_hint` collapses to ``""`` and trips
            `min_length=1`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | NotificationTemplateResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateCreate,
) -> HTTPValidationError | NotificationTemplateResponse | None:
    """Create Template

     Create a new shared notification template.

    Args:
        body (NotificationTemplateCreate): `str_strip_whitespace` runs before length validation,
            so a
            whitespace-only `channel_hint` collapses to ``""`` and trips
            `min_length=1`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | NotificationTemplateResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateCreate,
) -> Response[HTTPValidationError | NotificationTemplateResponse]:
    """Create Template

     Create a new shared notification template.

    Args:
        body (NotificationTemplateCreate): `str_strip_whitespace` runs before length validation,
            so a
            whitespace-only `channel_hint` collapses to ``""`` and trips
            `min_length=1`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | NotificationTemplateResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: NotificationTemplateCreate,
) -> HTTPValidationError | NotificationTemplateResponse | None:
    """Create Template

     Create a new shared notification template.

    Args:
        body (NotificationTemplateCreate): `str_strip_whitespace` runs before length validation,
            so a
            whitespace-only `channel_hint` collapses to ``""`` and trips
            `min_length=1`.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | NotificationTemplateResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
