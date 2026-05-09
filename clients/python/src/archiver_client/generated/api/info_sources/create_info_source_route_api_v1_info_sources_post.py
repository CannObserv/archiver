from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.info_source_create import InfoSourceCreate
from ...models.info_source_out import InfoSourceOut
from ...types import Response


def _get_kwargs(
    *,
    body: InfoSourceCreate,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/info-sources",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | InfoSourceOut | None:
    if response.status_code == 201:
        response_201 = InfoSourceOut.from_dict(response.json())

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
) -> Response[HTTPValidationError | InfoSourceOut]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: InfoSourceCreate,
) -> Response[HTTPValidationError | InfoSourceOut]:
    """Create Info Source Route

     Create a new InfoSource (root or fragment).

    A root source is created when ``parent_info_source_id`` is omitted; the
    submitted ``source_spec`` must carry ``target.url``. A fragment is created
    when ``parent_info_source_id`` is supplied; the spec must NOT carry
    ``target.url`` and the parent must itself be a root.

    Error responses:
    - 422: source_spec fails schema/shape validation, or
           ``parent_info_source_id`` is supplied but points at another fragment,
           or the path-shape ULID is malformed.
    - 404: ``parent_info_source_id`` references no existing InfoSource.
    - 409: a root with the same canonicalized URL already exists. The response
           body's ``existing_info_source_id`` is the row the operator should
           bind to instead.

    Args:
        body (InfoSourceCreate): Request body for POST /info-sources.

            A root source is created when ``parent_info_source_id`` is omitted; the
            ``source_spec`` must then carry ``target.url``. A fragment is created when
            ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
            ``target.url`` — fragments inherit URL/fetch semantics from the parent.

            ``schema_version`` is read from the embedded source_spec document; clients
            must not supply it separately.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoSourceOut]
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
    body: InfoSourceCreate,
) -> HTTPValidationError | InfoSourceOut | None:
    """Create Info Source Route

     Create a new InfoSource (root or fragment).

    A root source is created when ``parent_info_source_id`` is omitted; the
    submitted ``source_spec`` must carry ``target.url``. A fragment is created
    when ``parent_info_source_id`` is supplied; the spec must NOT carry
    ``target.url`` and the parent must itself be a root.

    Error responses:
    - 422: source_spec fails schema/shape validation, or
           ``parent_info_source_id`` is supplied but points at another fragment,
           or the path-shape ULID is malformed.
    - 404: ``parent_info_source_id`` references no existing InfoSource.
    - 409: a root with the same canonicalized URL already exists. The response
           body's ``existing_info_source_id`` is the row the operator should
           bind to instead.

    Args:
        body (InfoSourceCreate): Request body for POST /info-sources.

            A root source is created when ``parent_info_source_id`` is omitted; the
            ``source_spec`` must then carry ``target.url``. A fragment is created when
            ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
            ``target.url`` — fragments inherit URL/fetch semantics from the parent.

            ``schema_version`` is read from the embedded source_spec document; clients
            must not supply it separately.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoSourceOut
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: InfoSourceCreate,
) -> Response[HTTPValidationError | InfoSourceOut]:
    """Create Info Source Route

     Create a new InfoSource (root or fragment).

    A root source is created when ``parent_info_source_id`` is omitted; the
    submitted ``source_spec`` must carry ``target.url``. A fragment is created
    when ``parent_info_source_id`` is supplied; the spec must NOT carry
    ``target.url`` and the parent must itself be a root.

    Error responses:
    - 422: source_spec fails schema/shape validation, or
           ``parent_info_source_id`` is supplied but points at another fragment,
           or the path-shape ULID is malformed.
    - 404: ``parent_info_source_id`` references no existing InfoSource.
    - 409: a root with the same canonicalized URL already exists. The response
           body's ``existing_info_source_id`` is the row the operator should
           bind to instead.

    Args:
        body (InfoSourceCreate): Request body for POST /info-sources.

            A root source is created when ``parent_info_source_id`` is omitted; the
            ``source_spec`` must then carry ``target.url``. A fragment is created when
            ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
            ``target.url`` — fragments inherit URL/fetch semantics from the parent.

            ``schema_version`` is read from the embedded source_spec document; clients
            must not supply it separately.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | InfoSourceOut]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: InfoSourceCreate,
) -> HTTPValidationError | InfoSourceOut | None:
    """Create Info Source Route

     Create a new InfoSource (root or fragment).

    A root source is created when ``parent_info_source_id`` is omitted; the
    submitted ``source_spec`` must carry ``target.url``. A fragment is created
    when ``parent_info_source_id`` is supplied; the spec must NOT carry
    ``target.url`` and the parent must itself be a root.

    Error responses:
    - 422: source_spec fails schema/shape validation, or
           ``parent_info_source_id`` is supplied but points at another fragment,
           or the path-shape ULID is malformed.
    - 404: ``parent_info_source_id`` references no existing InfoSource.
    - 409: a root with the same canonicalized URL already exists. The response
           body's ``existing_info_source_id`` is the row the operator should
           bind to instead.

    Args:
        body (InfoSourceCreate): Request body for POST /info-sources.

            A root source is created when ``parent_info_source_id`` is omitted; the
            ``source_spec`` must then carry ``target.url``. A fragment is created when
            ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
            ``target.url`` — fragments inherit URL/fetch semantics from the parent.

            ``schema_version`` is read from the embedded source_spec document; clients
            must not supply it separately.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | InfoSourceOut
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
