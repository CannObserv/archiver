from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.assign_template_to_watch_api_v1_notifications_templates_template_id_assign_watch_id_post_response_assign_template_to_watch_api_v1_notifications_templates_template_id_assign_watch_id_post import (
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    template_id: str,
    watch_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/notifications/templates/{template_id}/assign/{watch_id}".format(
            template_id=quote(str(template_id), safe=""),
            watch_id=quote(str(watch_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
    | None
):
    if response.status_code == 201:
        response_201 = AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost.from_dict(
            response.json()
        )

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
) -> Response[
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    template_id: str,
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
]:
    """Assign Template To Watch

     Assign a notification template to a watch (idempotent).

    Args:
        template_id (str):
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        template_id=template_id,
        watch_id=watch_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    template_id: str,
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
    | None
):
    """Assign Template To Watch

     Assign a notification template to a watch (idempotent).

    Args:
        template_id (str):
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost | HTTPValidationError
    """

    return sync_detailed(
        template_id=template_id,
        watch_id=watch_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    template_id: str,
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> Response[
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
]:
    """Assign Template To Watch

     Assign a notification template to a watch (idempotent).

    Args:
        template_id (str):
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        template_id=template_id,
        watch_id=watch_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    template_id: str,
    watch_id: str,
    *,
    client: AuthenticatedClient,
) -> (
    AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost
    | HTTPValidationError
    | None
):
    """Assign Template To Watch

     Assign a notification template to a watch (idempotent).

    Args:
        template_id (str):
        watch_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPostResponseAssignTemplateToWatchApiV1NotificationsTemplatesTemplateIdAssignWatchIdPost | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            template_id=template_id,
            watch_id=watch_id,
            client=client,
        )
    ).parsed
