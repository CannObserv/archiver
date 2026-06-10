from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.test_template_api_v1_notifications_templates_template_id_test_post_response_test_template_api_v1_notifications_templates_template_id_test_post import (
    TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost,
)
from ...types import Response


def _get_kwargs(
    template_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/notifications/templates/{template_id}/test".format(
            template_id=quote(str(template_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
    | None
):
    if response.status_code == 200:
        response_200 = TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost.from_dict(
            response.json()
        )

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
) -> Response[
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
]:
    """Test Template

     Send a test notification using this template's configured remote channel.

    Args:
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost]
    """

    kwargs = _get_kwargs(
        template_id=template_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
    | None
):
    """Test Template

     Send a test notification using this template's configured remote channel.

    Args:
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
    """

    return sync_detailed(
        template_id=template_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
]:
    """Test Template

     Send a test notification using this template's configured remote channel.

    Args:
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost]
    """

    kwargs = _get_kwargs(
        template_id=template_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    template_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    HTTPValidationError
    | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
    | None
):
    """Test Template

     Send a test notification using this template's configured remote channel.

    Args:
        template_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | TestTemplateApiV1NotificationsTemplatesTemplateIdTestPostResponseTestTemplateApiV1NotificationsTemplatesTemplateIdTestPost
    """

    return (
        await asyncio_detailed(
            template_id=template_id,
            client=client,
        )
    ).parsed
