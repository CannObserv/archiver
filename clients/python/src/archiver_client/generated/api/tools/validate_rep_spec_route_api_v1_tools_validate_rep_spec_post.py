from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.validate_rep_spec_request import ValidateRepSpecRequest
from ...models.validate_rep_spec_response import ValidateRepSpecResponse
from ...types import Response


def _get_kwargs(
    *,
    body: ValidateRepSpecRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/tools/validate-rep-spec",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | ValidateRepSpecResponse | None:
    if response.status_code == 200:
        response_200 = ValidateRepSpecResponse.from_dict(response.json())

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
) -> Response[HTTPValidationError | ValidateRepSpecResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRepSpecRequest,
) -> Response[HTTPValidationError | ValidateRepSpecResponse]:
    """Validate Rep Spec Route

     Validate a RepSpec document against the v1 envelope + provider sub-schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateRepSpecRequest): Request body for POST /api/v1/tools/validate-rep-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ValidateRepSpecResponse]
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
    body: ValidateRepSpecRequest,
) -> HTTPValidationError | ValidateRepSpecResponse | None:
    """Validate Rep Spec Route

     Validate a RepSpec document against the v1 envelope + provider sub-schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateRepSpecRequest): Request body for POST /api/v1/tools/validate-rep-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ValidateRepSpecResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ValidateRepSpecRequest,
) -> Response[HTTPValidationError | ValidateRepSpecResponse]:
    """Validate Rep Spec Route

     Validate a RepSpec document against the v1 envelope + provider sub-schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateRepSpecRequest): Request body for POST /api/v1/tools/validate-rep-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | ValidateRepSpecResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ValidateRepSpecRequest,
) -> HTTPValidationError | ValidateRepSpecResponse | None:
    """Validate Rep Spec Route

     Validate a RepSpec document against the v1 envelope + provider sub-schema.

    Always returns 200 — the response body's ``valid`` flag carries the
    validation outcome, and ``errors`` carries field-level issues.

    Args:
        body (ValidateRepSpecRequest): Request body for POST /api/v1/tools/validate-rep-spec.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | ValidateRepSpecResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
