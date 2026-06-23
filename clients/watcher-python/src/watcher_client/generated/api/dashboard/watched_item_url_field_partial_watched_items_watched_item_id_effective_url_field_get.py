from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.watched_item_url_field_partial_watched_items_watched_item_id_effective_url_field_get_mode import (
    WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    watched_item_id: str,
    *,
    mode: WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode
    | Unset = WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_mode: str | Unset = UNSET
    if not isinstance(mode, Unset):
        json_mode = mode.value

    params["mode"] = json_mode

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/watched-items/{watched_item_id}/effective-url/field".format(
            watched_item_id=quote(str(watched_item_id), safe=""),
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
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    mode: WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode
    | Unset = WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Url Field Partial

     Serve the WatchedItem URL field partial in view or edit mode.

    Powers the inline Edit affordance on the detail page's URL row; the edit
    form posts to the sibling ``/effective-url`` route which re-probes.

    Args:
        watched_item_id (str):
        mode (WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode |
            Unset):  Default:
            WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        mode=mode,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    mode: WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode
    | Unset = WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW,
) -> Any | HTTPValidationError | None:
    """Watched Item Url Field Partial

     Serve the WatchedItem URL field partial in view or edit mode.

    Powers the inline Edit affordance on the detail page's URL row; the edit
    form posts to the sibling ``/effective-url`` route which re-probes.

    Args:
        watched_item_id (str):
        mode (WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode |
            Unset):  Default:
            WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        watched_item_id=watched_item_id,
        client=client,
        mode=mode,
    ).parsed


async def asyncio_detailed(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    mode: WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode
    | Unset = WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW,
) -> Response[Any | HTTPValidationError]:
    """Watched Item Url Field Partial

     Serve the WatchedItem URL field partial in view or edit mode.

    Powers the inline Edit affordance on the detail page's URL row; the edit
    form posts to the sibling ``/effective-url`` route which re-probes.

    Args:
        watched_item_id (str):
        mode (WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode |
            Unset):  Default:
            WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        watched_item_id=watched_item_id,
        mode=mode,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    watched_item_id: str,
    *,
    client: AuthenticatedClient | Client,
    mode: WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode
    | Unset = WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW,
) -> Any | HTTPValidationError | None:
    """Watched Item Url Field Partial

     Serve the WatchedItem URL field partial in view or edit mode.

    Powers the inline Edit affordance on the detail page's URL row; the edit
    form posts to the sibling ``/effective-url`` route which re-probes.

    Args:
        watched_item_id (str):
        mode (WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode |
            Unset):  Default:
            WatchedItemUrlFieldPartialWatchedItemsWatchedItemIdEffectiveUrlFieldGetMode.VIEW.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            watched_item_id=watched_item_id,
            client=client,
            mode=mode,
        )
    ).parsed
