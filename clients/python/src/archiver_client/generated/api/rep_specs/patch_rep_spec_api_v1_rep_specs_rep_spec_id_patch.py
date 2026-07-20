from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.envelope_response import EnvelopeResponse
from ...models.rep_spec_out import RepSpecOut
from ...models.rep_spec_patch import RepSpecPatch
from ...types import Response


def _get_kwargs(
    rep_spec_id: str,
    *,
    body: RepSpecPatch,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/api/v1/rep-specs/{rep_spec_id}".format(
            rep_spec_id=quote(str(rep_spec_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
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
    body: RepSpecPatch,
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Patch Rep Spec

     Update a RepSpec's name and/or document under the tiered contract.

    ``name`` is accepted regardless of assignment state. ``document`` is a
    whole-document replacement accepted only while the RepSpec is a draft.
    Omitting both fields is a no-op and does not stamp ``updated_at``.

    Error responses:
    - 404 ``lookup``: RepSpec not found
    - 409 ``conflict``: document edit on an assigned RepSpec; ``data.assignment_count``
      carries the number of assignment rows (active + deactivated) blocking it
    - 422 ``schema``: document failed validation, or attempted a provider change

    Args:
        rep_spec_id (str):
        body (RepSpecPatch): Request body for PATCH /rep-specs/{rep_spec_id}.

            Both fields are optional; omitted fields are left untouched. ``provider`` is
            absent by design — it is frozen for the life of the RepSpec, and supplying a
            ``document`` whose ``provider`` differs from the stored one is a 422.

            ``document`` is a whole-document *replacement*, not a merge patch: merge
            semantics cannot express key removal, which would make ``object_options``
            entries unremovable under the envelope's ``additionalProperties: false``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
    """

    kwargs = _get_kwargs(
        rep_spec_id=rep_spec_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
    body: RepSpecPatch,
) -> EnvelopeResponse | RepSpecOut | None:
    """Patch Rep Spec

     Update a RepSpec's name and/or document under the tiered contract.

    ``name`` is accepted regardless of assignment state. ``document`` is a
    whole-document replacement accepted only while the RepSpec is a draft.
    Omitting both fields is a no-op and does not stamp ``updated_at``.

    Error responses:
    - 404 ``lookup``: RepSpec not found
    - 409 ``conflict``: document edit on an assigned RepSpec; ``data.assignment_count``
      carries the number of assignment rows (active + deactivated) blocking it
    - 422 ``schema``: document failed validation, or attempted a provider change

    Args:
        rep_spec_id (str):
        body (RepSpecPatch): Request body for PATCH /rep-specs/{rep_spec_id}.

            Both fields are optional; omitted fields are left untouched. ``provider`` is
            absent by design — it is frozen for the life of the RepSpec, and supplying a
            ``document`` whose ``provider`` differs from the stored one is a 422.

            ``document`` is a whole-document *replacement*, not a merge patch: merge
            semantics cannot express key removal, which would make ``object_options``
            entries unremovable under the envelope's ``additionalProperties: false``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvelopeResponse | RepSpecOut
    """

    return sync_detailed(
        rep_spec_id=rep_spec_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
    body: RepSpecPatch,
) -> Response[EnvelopeResponse | RepSpecOut]:
    """Patch Rep Spec

     Update a RepSpec's name and/or document under the tiered contract.

    ``name`` is accepted regardless of assignment state. ``document`` is a
    whole-document replacement accepted only while the RepSpec is a draft.
    Omitting both fields is a no-op and does not stamp ``updated_at``.

    Error responses:
    - 404 ``lookup``: RepSpec not found
    - 409 ``conflict``: document edit on an assigned RepSpec; ``data.assignment_count``
      carries the number of assignment rows (active + deactivated) blocking it
    - 422 ``schema``: document failed validation, or attempted a provider change

    Args:
        rep_spec_id (str):
        body (RepSpecPatch): Request body for PATCH /rep-specs/{rep_spec_id}.

            Both fields are optional; omitted fields are left untouched. ``provider`` is
            absent by design — it is frozen for the life of the RepSpec, and supplying a
            ``document`` whose ``provider`` differs from the stored one is a 422.

            ``document`` is a whole-document *replacement*, not a merge patch: merge
            semantics cannot express key removal, which would make ``object_options``
            entries unremovable under the envelope's ``additionalProperties: false``.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvelopeResponse | RepSpecOut]
    """

    kwargs = _get_kwargs(
        rep_spec_id=rep_spec_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    rep_spec_id: str,
    *,
    client: AuthenticatedClient,
    body: RepSpecPatch,
) -> EnvelopeResponse | RepSpecOut | None:
    """Patch Rep Spec

     Update a RepSpec's name and/or document under the tiered contract.

    ``name`` is accepted regardless of assignment state. ``document`` is a
    whole-document replacement accepted only while the RepSpec is a draft.
    Omitting both fields is a no-op and does not stamp ``updated_at``.

    Error responses:
    - 404 ``lookup``: RepSpec not found
    - 409 ``conflict``: document edit on an assigned RepSpec; ``data.assignment_count``
      carries the number of assignment rows (active + deactivated) blocking it
    - 422 ``schema``: document failed validation, or attempted a provider change

    Args:
        rep_spec_id (str):
        body (RepSpecPatch): Request body for PATCH /rep-specs/{rep_spec_id}.

            Both fields are optional; omitted fields are left untouched. ``provider`` is
            absent by design — it is frozen for the life of the RepSpec, and supplying a
            ``document`` whose ``provider`` differs from the stored one is a 422.

            ``document`` is a whole-document *replacement*, not a merge patch: merge
            semantics cannot express key removal, which would make ``object_options``
            entries unremovable under the envelope's ``additionalProperties: false``.

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
            body=body,
        )
    ).parsed
