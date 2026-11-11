from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.info_source_capture_policy_patch import InfoSourceCapturePolicyPatch
from ...models.info_source_out import InfoSourceOut
from ...types import Response


def _get_kwargs(
    info_source_id: str,
    *,
    body: InfoSourceCapturePolicyPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/info-sources/{info_source_id}/capture-policy".format(
            info_source_id=quote(str(info_source_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EnvelopeResponse | InfoSourceOut | None:
    if response.status_code == 200:
        response_200 = InfoSourceOut.from_dict(response.json())

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
) -> Response[EnvelopeResponse | InfoSourceOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoSourceCapturePolicyPatch,
) -> Response[EnvelopeResponse | InfoSourceOut]:
    """Patch Info Source Capture Policy

     Set or clear the InfoSource's viewport-capture policy (archiver#380).

    Replaced whole: omitted keys take their defaults, so the response shows the
    stored document. ``on_revision: true`` captures each new revision; ``null``
    clears the policy. Takes effect at the next capture; sends nothing itself.

    Args:
        info_source_id (str):
        body (InfoSourceCapturePolicyPatch): Request body for PATCH /info-sources/{id}/capture-
            policy.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoSourceOut]
    """

    kwargs = _get_kwargs(
        info_source_id=info_source_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoSourceCapturePolicyPatch,
) -> EnvelopeResponse | InfoSourceOut | None:
    """Patch Info Source Capture Policy

     Set or clear the InfoSource's viewport-capture policy (archiver#380).

    Replaced whole: omitted keys take their defaults, so the response shows the
    stored document. ``on_revision: true`` captures each new revision; ``null``
    clears the policy. Takes effect at the next capture; sends nothing itself.

    Args:
        info_source_id (str):
        body (InfoSourceCapturePolicyPatch): Request body for PATCH /info-sources/{id}/capture-
            policy.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoSourceOut
    """

    return sync_detailed(
        info_source_id=info_source_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoSourceCapturePolicyPatch,
) -> Response[EnvelopeResponse | InfoSourceOut]:
    """Patch Info Source Capture Policy

     Set or clear the InfoSource's viewport-capture policy (archiver#380).

    Replaced whole: omitted keys take their defaults, so the response shows the
    stored document. ``on_revision: true`` captures each new revision; ``null``
    clears the policy. Takes effect at the next capture; sends nothing itself.

    Args:
        info_source_id (str):
        body (InfoSourceCapturePolicyPatch): Request body for PATCH /info-sources/{id}/capture-
            policy.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | InfoSourceOut]
    """

    kwargs = _get_kwargs(
        info_source_id=info_source_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    info_source_id: str,
    *,
    client: AuthenticatedClient,
    body: InfoSourceCapturePolicyPatch,
) -> EnvelopeResponse | InfoSourceOut | None:
    """Patch Info Source Capture Policy

     Set or clear the InfoSource's viewport-capture policy (archiver#380).

    Replaced whole: omitted keys take their defaults, so the response shows the
    stored document. ``on_revision: true`` captures each new revision; ``null``
    clears the policy. Takes effect at the next capture; sends nothing itself.

    Args:
        info_source_id (str):
        body (InfoSourceCapturePolicyPatch): Request body for PATCH /info-sources/{id}/capture-
            policy.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | InfoSourceOut
    """

    return (
        await asyncio_detailed(
            info_source_id=info_source_id,
            client=client,
            body=body,
        )
    ).parsed
