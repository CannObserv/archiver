from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.info_item_rep_spec_out import InfoItemRepSpecOut
from ...models.info_item_rep_spec_public_url_patch import InfoItemRepSpecPublicUrlPatch
from ...types import Response


def _get_kwargs(
    info_item_id: str,
    assignment_id: str,
    *,
    body: InfoItemRepSpecPublicUrlPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/info-items/{info_item_id}/rep-spec-assignments/{assignment_id}".format(
            info_item_id=quote(str(info_item_id), safe=""),
            assignment_id=quote(str(assignment_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InfoItemRepSpecOut | None:
    if response.status_code == 200:
        response_200 = InfoItemRepSpecOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | InfoItemRepSpecOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemRepSpecPublicUrlPatch,
) -> Response[HTTPValidationError | InfoItemRepSpecOut]:
    """Patch Rep Spec Assignment Public Url

     Write a provider-native public URL back to a RepSpec assignment.

    Called by Replicator after a successful replication job. Works on both
    active and deactivated rows (history preservation). Returns 404 if the
    assignment doesn't exist or doesn't belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):
        body (InfoItemRepSpecPublicUrlPatch): Request body for PATCH /info-items/{id}/rep-spec-
            assignments/{assignment_id}.

            Writes the provider-native public URL back to an assignment row (active or
            deactivated). Called by Replicator after a successful replication job.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemRepSpecOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemRepSpecPublicUrlPatch,
) -> HTTPValidationError | InfoItemRepSpecOut | None:
    """Patch Rep Spec Assignment Public Url

     Write a provider-native public URL back to a RepSpec assignment.

    Called by Replicator after a successful replication job. Works on both
    active and deactivated rows (history preservation). Returns 404 if the
    assignment doesn't exist or doesn't belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):
        body (InfoItemRepSpecPublicUrlPatch): Request body for PATCH /info-items/{id}/rep-spec-
            assignments/{assignment_id}.

            Writes the provider-native public URL back to an assignment row (active or
            deactivated). Called by Replicator after a successful replication job.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemRepSpecOut
    """

    return sync_detailed(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemRepSpecPublicUrlPatch,
) -> Response[HTTPValidationError | InfoItemRepSpecOut]:
    """Patch Rep Spec Assignment Public Url

     Write a provider-native public URL back to a RepSpec assignment.

    Called by Replicator after a successful replication job. Works on both
    active and deactivated rows (history preservation). Returns 404 if the
    assignment doesn't exist or doesn't belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):
        body (InfoItemRepSpecPublicUrlPatch): Request body for PATCH /info-items/{id}/rep-spec-
            assignments/{assignment_id}.

            Writes the provider-native public URL back to an assignment row (active or
            deactivated). Called by Replicator after a successful replication job.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoItemRepSpecOut]
    """

    kwargs = _get_kwargs(
        info_item_id=info_item_id,
        assignment_id=assignment_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_item_id: str,
    assignment_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoItemRepSpecPublicUrlPatch,
) -> HTTPValidationError | InfoItemRepSpecOut | None:
    """Patch Rep Spec Assignment Public Url

     Write a provider-native public URL back to a RepSpec assignment.

    Called by Replicator after a successful replication job. Works on both
    active and deactivated rows (history preservation). Returns 404 if the
    assignment doesn't exist or doesn't belong to the given InfoItem.

    Args:
        info_item_id (str):
        assignment_id (str):
        body (InfoItemRepSpecPublicUrlPatch): Request body for PATCH /info-items/{id}/rep-spec-
            assignments/{assignment_id}.

            Writes the provider-native public URL back to an assignment row (active or
            deactivated). Called by Replicator after a successful replication job.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoItemRepSpecOut
    """

    return (
        await asyncio_detailed(
            info_item_id=info_item_id,
            assignment_id=assignment_id,
            client=client,
            body=body,
        )
    ).parsed
