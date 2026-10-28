"""``ArchiverClient`` — public facade.

Wraps a single httpx.AsyncClient with X-API-Key auth and exposes ergonomic
methods that dispatch to the generated openapi-python-client output for
typed request/response handling.

The generated package's naming is verbose (FastAPI default operation IDs),
so callers should use this wrapper instead of importing from
``archiver_client.generated`` directly.

Async-only. No sync facade.
"""

from __future__ import annotations

import datetime
from types import TracebackType
from typing import Any

import httpx

from archiver_client import tools as _tools
from archiver_client.errors import error_from_response
from archiver_client.generated.api.domains import (
    archive_domain_api_v1_domains_name_archive_post as _archive_domain,
)
from archiver_client.generated.api.domains import (
    delete_domain_api_v1_domains_name_delete as _delete_domain,
)
from archiver_client.generated.api.domains import (
    get_domain_api_v1_domains_name_get as _get_domain,
)
from archiver_client.generated.api.domains import (
    list_domains_api_v1_domains_get as _list_domains,
)
from archiver_client.generated.api.domains import (
    restore_domain_api_v1_domains_name_restore_post as _restore_domain,
)
from archiver_client.generated.api.domains import (
    upsert_domain_api_v1_domains_name_patch as _upsert_domain,
)
from archiver_client.generated.api.info_items import (
    add_info_source_api_v1_info_items_info_item_id_info_sources_post as _add_info_source,
)
from archiver_client.generated.api.info_items import (
    add_rep_spec_assignment_api_v1_info_items_info_item_id_rep_spec_assignments_post as _add_rep_spec,
)
from archiver_client.generated.api.info_items import (
    archive_info_item_api_v1_info_items_info_item_id_archive_post as _archive_info_item,
)
from archiver_client.generated.api.info_items import (
    create_info_item_api_v1_info_items_post as _create_info_item,
)
from archiver_client.generated.api.info_items import (
    deactivate_info_source_binding_api_v1_info_items_info_item_id_info_sources_info_source_id_delete as _deactivate_info_source_binding,
)
from archiver_client.generated.api.info_items import (
    deactivate_rep_spec_assignment_api_v1_info_items_info_item_id_rep_spec_assignments_assignment_id_delete as _deactivate_rep_spec,
)
from archiver_client.generated.api.info_items import (
    delete_info_item_api_v1_info_items_info_item_id_delete as _delete_info_item,
)
from archiver_client.generated.api.info_items import (
    delete_temporal_profile_api_v1_info_items_info_item_id_temporal_profile_delete as _delete_temporal_profile,
)
from archiver_client.generated.api.info_items import (
    get_info_item_api_v1_info_items_info_item_id_get as _get_info_item,
)
from archiver_client.generated.api.info_items import (
    get_temporal_profile_api_v1_info_items_info_item_id_temporal_profile_get as _get_temporal_profile,
)
from archiver_client.generated.api.info_items import (
    list_info_items_api_v1_info_items_get as _list_info_items,
)
from archiver_client.generated.api.info_items import (
    patch_rep_spec_assignment_public_url_api_v1_info_items_info_item_id_rep_spec_assignments_assignment_id_patch as _patch_rep_spec_url,
)
from archiver_client.generated.api.info_items import (
    put_org_api_v1_info_items_info_item_id_org_put as _put_org,
)
from archiver_client.generated.api.info_items import (
    put_primary_source_api_v1_info_items_info_item_id_primary_source_put as _put_primary_source,
)
from archiver_client.generated.api.info_items import (
    put_rep_fields_api_v1_info_items_info_item_id_rep_fields_put as _put_rep_fields,
)
from archiver_client.generated.api.info_items import (
    put_temporal_profile_api_v1_info_items_info_item_id_temporal_profile_put as _put_temporal_profile,
)
from archiver_client.generated.api.info_items import (
    put_watch_spec_api_v1_info_items_info_item_id_watch_spec_put as _put_watch_spec,
)
from archiver_client.generated.api.info_items import (
    restore_info_item_api_v1_info_items_info_item_id_restore_post as _restore_info_item,
)
from archiver_client.generated.api.info_sources import (
    create_info_source_route_api_v1_info_sources_post as _create_info_source,
)
from archiver_client.generated.api.info_sources import (
    get_info_source_api_v1_info_sources_info_source_id_get as _get_info_source,
)
from archiver_client.generated.api.info_sources import (
    list_info_sources_api_v1_info_sources_get as _list_info_sources,
)
from archiver_client.generated.api.info_sources import (
    patch_info_source_specs_api_v1_info_sources_info_source_id_source_specs_patch as _patch_info_source_specs,
)
from archiver_client.generated.api.notification_subscriptions import (
    create_notification_subscription_api_v1_notification_subscriptions_post as _create_subscription,
)
from archiver_client.generated.api.notification_subscriptions import (
    delete_notification_subscription_api_v1_notification_subscriptions_subscription_id_delete as _delete_subscription,
)
from archiver_client.generated.api.notification_subscriptions import (
    get_notification_subscription_api_v1_notification_subscriptions_subscription_id_get as _get_subscription,
)
from archiver_client.generated.api.notification_subscriptions import (
    list_notification_subscriptions_api_v1_notification_subscriptions_get as _list_subscriptions,
)
from archiver_client.generated.api.notification_subscriptions import (
    update_notification_subscription_api_v1_notification_subscriptions_subscription_id_patch as _update_subscription,
)
from archiver_client.generated.api.rep_specs import (
    create_rep_spec_route_api_v1_rep_specs_post as _create_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    get_rep_spec_api_v1_rep_specs_rep_spec_id_get as _get_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    list_rep_specs_api_v1_rep_specs_get as _list_rep_specs,
)
from archiver_client.generated.api.rep_specs import (
    patch_rep_spec_api_v1_rep_specs_rep_spec_id_patch as _patch_rep_spec,
)
from archiver_client.generated.api.source_revisions import (
    create_source_revision_api_v1_source_revisions_post as _create_source_revision,
)
from archiver_client.generated.api.source_revisions import (
    patch_source_revision_api_v1_source_revisions_source_revision_id_patch as _patch_source_revision,
)
from archiver_client.generated.client import AuthenticatedClient
from archiver_client.generated.models.domain_out import DomainOut
from archiver_client.generated.models.domain_patch import DomainPatch
from archiver_client.generated.models.domain_patch_default_watch_spec_type_0 import (
    DomainPatchDefaultWatchSpecType0,
)
from archiver_client.generated.models.info_item_create import InfoItemCreate
from archiver_client.generated.models.info_item_create_initial_source_specs_type_0_item import (
    InfoItemCreateInitialSourceSpecsType0Item,
)
from archiver_client.generated.models.info_item_create_rep_fields import InfoItemCreateRepFields
from archiver_client.generated.models.info_item_org_put import InfoItemOrgPut
from archiver_client.generated.models.info_item_out import InfoItemOut
from archiver_client.generated.models.info_item_primary_source_put import (
    InfoItemPrimarySourcePut,
)
from archiver_client.generated.models.info_item_rep_fields_put import InfoItemRepFieldsPut
from archiver_client.generated.models.info_item_rep_fields_put_rep_fields import (
    InfoItemRepFieldsPutRepFields,
)
from archiver_client.generated.models.info_item_rep_spec_create import InfoItemRepSpecCreate
from archiver_client.generated.models.info_item_rep_spec_out import InfoItemRepSpecOut
from archiver_client.generated.models.info_item_rep_spec_public_url_patch import (
    InfoItemRepSpecPublicUrlPatch,
)
from archiver_client.generated.models.info_item_source_create import InfoItemSourceCreate
from archiver_client.generated.models.info_item_source_out import InfoItemSourceOut
from archiver_client.generated.models.info_item_watch_spec_put import InfoItemWatchSpecPut
from archiver_client.generated.models.info_item_watch_spec_put_document import (
    InfoItemWatchSpecPutDocument,
)
from archiver_client.generated.models.info_source_create import InfoSourceCreate
from archiver_client.generated.models.info_source_create_source_specs_item import (
    InfoSourceCreateSourceSpecsItem,
)
from archiver_client.generated.models.info_source_out import InfoSourceOut
from archiver_client.generated.models.info_source_patch import InfoSourcePatch
from archiver_client.generated.models.info_source_patch_source_specs_item import (
    InfoSourcePatchSourceSpecsItem,
)
from archiver_client.generated.models.list_notification_subscriptions_api_v1_notification_subscriptions_get_scope_type_0 import (
    ListNotificationSubscriptionsApiV1NotificationSubscriptionsGetScopeType0 as _SubscriptionScope,
)
from archiver_client.generated.models.notification_subscription_create import (
    NotificationSubscriptionCreate,
)
from archiver_client.generated.models.notification_subscription_out import (
    NotificationSubscriptionOut,
)
from archiver_client.generated.models.notification_subscription_patch import (
    NotificationSubscriptionPatch,
)
from archiver_client.generated.models.page_domain_out import PageDomainOut
from archiver_client.generated.models.page_info_item_out import PageInfoItemOut
from archiver_client.generated.models.page_info_source_out import PageInfoSourceOut
from archiver_client.generated.models.page_notification_subscription_out import (
    PageNotificationSubscriptionOut,
)
from archiver_client.generated.models.page_rep_spec_out import PageRepSpecOut
from archiver_client.generated.models.rep_spec_assignment_create import RepSpecAssignmentCreate
from archiver_client.generated.models.rep_spec_create import RepSpecCreate
from archiver_client.generated.models.rep_spec_create_document import RepSpecCreateDocument
from archiver_client.generated.models.rep_spec_out import RepSpecOut
from archiver_client.generated.models.rep_spec_patch import RepSpecPatch
from archiver_client.generated.models.rep_spec_patch_document_type_0 import (
    RepSpecPatchDocumentType0,
)
from archiver_client.generated.models.source_revision_cache_patch import SourceRevisionCachePatch
from archiver_client.generated.models.source_revision_create import SourceRevisionCreate
from archiver_client.generated.models.source_revision_out import SourceRevisionOut
from archiver_client.generated.models.temporal_profile_out import TemporalProfileOut
from archiver_client.generated.models.temporal_profile_put import TemporalProfilePut
from archiver_client.generated.types import UNSET


class ArchiverClient:
    """Async client for the Archiver service."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._mask = (api_key[:3] + "***") if api_key else "***"
        self._cache_ttl_seconds = cache_ttl_seconds
        self._gen_client = AuthenticatedClient(
            base_url=self._base_url,
            token=api_key,
            auth_header_name="X-API-Key",
            prefix="",
            timeout=httpx.Timeout(timeout),
            raise_on_unexpected_status=False,
        )

    def __repr__(self) -> str:
        return f"ArchiverClient(base_url={self._base_url!r}, api_key={self._mask!r})"

    async def __aenter__(self) -> ArchiverClient:
        await self._gen_client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._gen_client.__aexit__(exc_type, exc, tb)

    async def aclose(self) -> None:
        """Close the underlying generated client (mirrors ``async with`` exit)."""
        await self._gen_client.__aexit__(None, None, None)

    # --- InfoItem endpoints ---

    async def create_info_item(
        self,
        *,
        name: str,
        description: str | None = None,
        owner: str | None = None,
        rep_fields: dict | None = None,
        initial_url: str | None = None,
        initial_source_specs: list[dict] | None = None,
        initial_rep_spec_assignments: list[dict] | None = None,
        pm_org_id: str | None = None,
    ) -> InfoItemOut:
        """Create a new InfoItem.

        ``initial_url`` and ``initial_source_specs`` atomically create a primary
        InfoSource alongside the InfoItem. ``initial_rep_spec_assignments``
        atomically creates RepSpec assignment rows. ``pm_org_id`` links a Power
        Map org, fetched at create; ``rep_fields`` may then not carry
        ``org.title``/``org.acronym``, and Power Map unreachable raises
        ``ServerError`` (503). A listed RepSpec whose document fails validation
        raises ``ValidationError`` (422, ``code="rep_spec_invalid"``). On
        validation failure, no rows are persisted.
        """
        body = InfoItemCreate(name=name, description=description, owner=owner)
        if rep_fields is not None:
            body.rep_fields = InfoItemCreateRepFields.from_dict(rep_fields)
        if pm_org_id is not None:
            body.pm_org_id = pm_org_id
        if initial_url is not None:
            body.initial_url = initial_url
        if initial_source_specs is not None:
            body.initial_source_specs = [
                InfoItemCreateInitialSourceSpecsType0Item.from_dict(s) for s in initial_source_specs
            ]
        if initial_rep_spec_assignments is not None:
            body.initial_rep_spec_assignments = [
                RepSpecAssignmentCreate.from_dict(a) for a in initial_rep_spec_assignments
            ]
        response = await _create_info_item.asyncio_detailed(client=self._gen_client, body=body)
        return _unwrap(response)

    async def list_info_items(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        archived: bool | None = None,
    ) -> PageInfoItemOut:
        """List InfoItems as a paginated envelope.

        ``limit`` and ``offset`` are forwarded to the server when set; omit to
        accept server defaults (limit=100, offset=0). Server caps ``limit`` at
        500. ``archived`` filters on the watch's archived state (archiver#361);
        omitted returns both. The returned ``PageInfoItemOut`` carries
        ``items``, ``has_more``, ``limit``, and ``offset``.
        """
        response = await _list_info_items.asyncio_detailed(
            client=self._gen_client,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
            archived=UNSET if archived is None else archived,
        )
        return _unwrap(response)

    async def get_info_item(
        self, info_item_id: str, *, include_deactivated: bool = False
    ) -> InfoItemOut:
        """Fetch a single InfoItem by ID.

        Pass ``include_deactivated=True`` to also include previous primaries and
        other deactivated source bindings in ``info_item_sources``.
        """
        response = await _get_info_item.asyncio_detailed(
            client=self._gen_client,
            info_item_id=info_item_id,
            include_deactivated=include_deactivated,
        )
        return _unwrap(response)

    async def delete_info_item(self, info_item_id: str) -> None:
        """Delete an InfoItem, cascading its bindings and RepSpec assignments.

        The registry's only exit for an InfoItem (archiver#141) — it exists so
        that leaving the registry has a transactional home, since the announced
        form of "gone" is a ``revoked`` tombstone that must be written in the
        deletion's own transaction. The InfoSource and its SourceRevisions are
        untouched: the physical layer is shared.

        404 on an already-deleted item rather than a silent success.
        """
        response = await _delete_info_item.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
        )
        _unwrap_no_content(response)

    async def set_rep_fields(
        self,
        info_item_id: str,
        rep_fields: dict[str, Any],
        *,
        allow_destination_change: bool = False,
    ) -> InfoItemOut:
        """Replace an InfoItem's whole ``rep_fields`` bag (not a merge).

        Checked against every active RepSpec assignment before it is stored;
        any refusal leaves the stored bag unchanged. Raises ``NotFound``,
        ``ValidationError`` (422: not Rep Fields v1, ``code="rep_fields_invalid"``;
        or it would break an assignment, ``rep_fields_incomplete`` /
        ``rep_fields_unrenderable``, every one named in ``data.refusals``), or
        ``Conflict`` (409, ``rep_fields_moves_destination``: valid, but an
        assignment would render to a new path from now on; ``data.moves`` holds
        each path before and after - pass ``allow_destination_change=True`` to
        store it anyway).
        """
        body = InfoItemRepFieldsPut(
            rep_fields=InfoItemRepFieldsPutRepFields.from_dict(rep_fields),
            allow_destination_change=allow_destination_change,
        )
        response = await _put_rep_fields.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    async def set_watch_spec(self, info_item_id: str, document: dict[str, Any]) -> InfoItemOut:
        """Replace an InfoItem's own cadence document, a WatchSpec v1 (not a merge).

        Omitting ``interval`` makes the item inherit: its host's default cadence,
        else Watcher's. The announcement carries the resolved interval, so the
        returned ``watch_spec`` is the item's own document, not what was
        announced. Raises ``NotFound`` or ``ValidationError`` (422, the stored
        document unchanged).
        """
        body = InfoItemWatchSpecPut(document=InfoItemWatchSpecPutDocument.from_dict(document))
        response = await _put_watch_spec.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    async def archive_info_item(self, info_item_id: str) -> InfoItemOut:
        """Archive an InfoItem's watch; it is announced inactive (archiver#361).

        The item keeps its own ``watch_active``, which ``restore_info_item``
        returns it to. Idempotent: an archived item keeps its first
        ``archived_at``. Raises ``NotFound``.
        """
        response = await _archive_info_item.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
        )
        return _unwrap(response)

    async def restore_info_item(self, info_item_id: str) -> InfoItemOut:
        """Clear an InfoItem's archive; it is announced with its own ``watch_active``.

        A paused item stays paused. A no-op on an item that is not archived.
        Raises ``NotFound``.
        """
        response = await _restore_info_item.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
        )
        return _unwrap(response)

    async def get_temporal_profile(self, info_item_id: str) -> TemporalProfileOut:
        """An InfoItem's temporal profile (archiver#365). Raises ``NotFound`` when the
        item or its profile is missing."""
        response = await _get_temporal_profile.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
        )
        return _unwrap(response)

    async def set_temporal_profile(
        self, info_item_id: str, profile: dict[str, Any]
    ) -> TemporalProfileOut:
        """Create or replace an InfoItem's temporal profile (the whole document).

        ``profile`` is the ``TemporalProfilePut`` body: ``profile_type``,
        ``reference_date`` or ``date_range_start``/``date_range_end`` (ISO
        dates, UTC days), ``rules``, ``post_action``, optional ``is_active``.
        Evaluated for today on write: ``resolved_interval`` is what the item now
        announces at the top of its cadence. Every write re-arms the
        post-action, so a window that has already ended is refused. Raises
        ``NotFound`` or ``ValidationError`` (422, nothing stored).
        """
        response = await _put_temporal_profile.asyncio_detailed(
            client=self._gen_client,
            info_item_id=info_item_id,
            body=TemporalProfilePut.from_dict(profile),
        )
        return _unwrap(response)

    async def delete_temporal_profile(self, info_item_id: str) -> None:
        """Delete an InfoItem's temporal profile; the item's own or its host's
        cadence takes over. Raises ``NotFound``."""
        response = await _delete_temporal_profile.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
        )
        _unwrap_no_content(response)

    async def set_org(
        self,
        info_item_id: str,
        pm_org_id: str | None,
        *,
        allow_destination_change: bool = False,
    ) -> InfoItemOut:
        """Link an InfoItem to a Power Map org, or unlink it with ``None``.

        Linking fetches the org from Power Map and snapshots it; the item's
        ``org.title``/``org.acronym`` then come from the org (stored copies are
        dropped). Unlinking writes the org's values back into ``rep_fields`` so
        no path moves. Raises ``NotFound``, ``ServerError`` (503: Power Map not
        configured or unreachable; ``data.reason``), ``ValidationError`` (422:
        ``pm_org_not_found`` / ``pm_org_unnamed``, or an assignment would break,
        ``data.refusals``), or ``Conflict`` (409, ``rep_fields_moves_destination``;
        ``data.moves`` - pass ``allow_destination_change=True`` to store it).
        """
        body = InfoItemOrgPut(
            pm_org_id=pm_org_id, allow_destination_change=allow_destination_change
        )
        response = await _put_org.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    # --- RepSpec assignment endpoints ---

    async def assign_rep_spec(
        self,
        info_item_id: str,
        rep_spec_id: str,
        *,
        activated_at: datetime.datetime | None = None,
    ) -> InfoItemRepSpecOut:
        """Assign a RepSpec to an InfoItem.

        ``activated_at`` defaults to now() when omitted. Raises ``NotFound``
        (unknown item or spec), ``Conflict`` (409: the spec is already actively
        assigned to this item; ``data.existing_assignment_id`` names it -
        deactivate it first), or ``ValidationError`` (422: the spec's document
        fails validation, ``code="rep_spec_invalid"``, paths under ``/document``;
        ``rep_fields`` lacks a required field, ``code="rep_fields_incomplete"``;
        or cannot render the spec's ``path_template``,
        ``code="rep_fields_unrenderable"``).
        """
        body = InfoItemRepSpecCreate(
            rep_spec_id=rep_spec_id,
            activated_at=activated_at if activated_at is not None else UNSET,
        )
        response = await _add_rep_spec.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    async def deactivate_rep_spec_assignment(self, info_item_id: str, assignment_id: str) -> None:
        """Deactivate (soft-delete) a RepSpec assignment."""
        response = await _deactivate_rep_spec.asyncio_detailed(
            client=self._gen_client,
            info_item_id=info_item_id,
            assignment_id=assignment_id,
        )
        _unwrap_no_content(response)

    async def set_public_url(
        self, info_item_id: str, assignment_id: str, public_url: str
    ) -> InfoItemRepSpecOut:
        """Write the provider-native public URL back to a RepSpec assignment."""
        body = InfoItemRepSpecPublicUrlPatch(public_url=public_url)
        response = await _patch_rep_spec_url.asyncio_detailed(
            client=self._gen_client,
            info_item_id=info_item_id,
            assignment_id=assignment_id,
            body=body,
        )
        return _unwrap(response)

    # --- RepSpec endpoints ---

    async def create_rep_spec(
        self,
        *,
        provider: str,
        name: str,
        document: dict,
    ) -> RepSpecOut:
        """Author a new RepSpec.

        Validates against the v1 envelope + per-provider sub-schema server-side.
        Raises ``ValidationError`` if either fails. Returns the persisted row.
        """
        body = RepSpecCreate(
            provider=provider,
            name=name,
            document=RepSpecCreateDocument.from_dict(document),
        )
        response = await _create_rep_spec.asyncio_detailed(client=self._gen_client, body=body)
        return _unwrap(response)

    async def update_rep_spec(
        self,
        rep_spec_id: str,
        *,
        name: str | None = None,
        document: dict | None = None,
    ) -> RepSpecOut:
        """Update a RepSpec's name and/or document under the tiered contract.

        ``name`` is accepted regardless of assignment state. ``document`` is a
        whole-document *replacement* accepted only while the RepSpec is a draft
        — zero assignment rows, active or deactivated. ``provider`` cannot be
        changed; supplying a document with a different provider is a
        ``ValidationError``.

        Omitted arguments are left untouched; omitting both is a server-side
        no-op that does not stamp ``updated_at``.

        Raises ``NotFound`` (unknown ID), ``Conflict`` (document edit on an
        assigned RepSpec — ``data["assignment_count"]`` carries the number of
        assignment rows blocking it), or ``ValidationError`` (schema failure or
        attempted provider change).
        """
        body = RepSpecPatch(
            name=UNSET if name is None else name,
            document=(UNSET if document is None else RepSpecPatchDocumentType0.from_dict(document)),
        )
        response = await _patch_rep_spec.asyncio_detailed(
            client=self._gen_client, rep_spec_id=rep_spec_id, body=body
        )
        return _unwrap(response)

    async def get_rep_spec(self, rep_spec_id: str) -> RepSpecOut:
        """Fetch a single RepSpec by ID."""
        response = await _get_rep_spec.asyncio_detailed(
            client=self._gen_client, rep_spec_id=rep_spec_id
        )
        return _unwrap(response)

    async def list_rep_specs(
        self,
        *,
        provider: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PageRepSpecOut:
        """List RepSpecs as a paginated envelope.

        ``provider`` restricts to a single provider key. ``limit``/``offset`` are
        forwarded when set; omit to accept server defaults (limit=100, offset=0).
        Server caps ``limit`` at 500.
        """
        response = await _list_rep_specs.asyncio_detailed(
            client=self._gen_client,
            provider=provider if provider is not None else UNSET,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    # --- InfoSource binding ---

    async def add_info_source(
        self,
        info_item_id: str,
        info_source_id: str,
    ) -> InfoItemSourceOut:
        """Bind an InfoSource to an InfoItem that has no active primary.

        At most one active binding per InfoItem. Raises ``Conflict`` if an active
        binding already exists. To replace a primary, use
        ``replace_primary_source``: deactivating then re-adding is not a swap
        (archiver#45).
        """
        body = InfoItemSourceCreate(info_source_id=info_source_id)
        response = await _add_info_source.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    async def deactivate_info_source_binding(
        self,
        info_item_id: str,
        info_source_id: str,
    ) -> InfoItemSourceOut:
        """Deactivate an InfoItemSource binding (sets ``deactivated_at``).

        Retires the primary and leaves the item with none. To replace a primary,
        use ``replace_primary_source`` instead (archiver#45).
        Returns the deactivated binding row. Raises on 404.
        """
        response = await _deactivate_info_source_binding.asyncio_detailed(
            client=self._gen_client,
            info_item_id=info_item_id,
            info_source_id=info_source_id,
        )
        return _unwrap(response)

    async def replace_primary_source(
        self,
        info_item_id: str,
        info_source_id: str,
    ) -> InfoItemSourceOut:
        """Make ``info_source_id`` the item's primary, retiring the current one.

        One request, one transaction, one ``info.registry`` announcement
        (archiver#45). Deactivating and then re-adding announces revoked and
        then live, and the consumer destroys and recreates its row in between.
        Already-primary is a no-op; an earlier primary of this item starts a
        new tenure, a binding with a new ``id``. Raises ``NotFound`` for an
        unknown item or source.
        """
        body = InfoItemPrimarySourcePut(info_source_id=info_source_id)
        response = await _put_primary_source.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    # --- Top-level InfoSource endpoints ---

    async def create_info_source(
        self,
        url: str,
        source_specs: list[dict],
    ) -> InfoSourceOut:
        """Author a new InfoSource.

        ``url`` is the URL to fetch (immutable after creation). ``source_specs``
        is the ordered list of extraction specs; first element is primary,
        subsequent elements are cross-check alternatives.
        """
        body = InfoSourceCreate(
            url=url,
            source_specs=[InfoSourceCreateSourceSpecsItem.from_dict(s) for s in source_specs],
        )
        response = await _create_info_source.asyncio_detailed(client=self._gen_client, body=body)
        return _unwrap(response)

    async def update_info_source_specs(
        self,
        info_source_id: str,
        source_specs: list[dict],
    ) -> InfoSourceOut:
        """Replace the source_specs list on an existing InfoSource.

        URL is immutable; only source_specs may be updated.
        """
        body = InfoSourcePatch(
            source_specs=[InfoSourcePatchSourceSpecsItem.from_dict(s) for s in source_specs],
        )
        response = await _patch_info_source_specs.asyncio_detailed(
            client=self._gen_client, info_source_id=info_source_id, body=body
        )
        return _unwrap(response)

    async def get_info_source(self, info_source_id: str) -> InfoSourceOut:
        """Fetch a single InfoSource by ID."""
        response = await _get_info_source.asyncio_detailed(
            client=self._gen_client, info_source_id=info_source_id
        )
        return _unwrap(response)

    async def list_info_sources(
        self,
        *,
        url: str | None = None,
        domain_name: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PageInfoSourceOut:
        """List InfoSources as a paginated envelope.

        ``url`` filters to exact URL matches; ``domain_name`` filters to a
        single hostname. ``limit``/``offset`` are forwarded when set; omit to
        accept server defaults (limit=100, offset=0). Server caps ``limit``
        at 500.
        """
        response = await _list_info_sources.asyncio_detailed(
            client=self._gen_client,
            url_query=url if url is not None else UNSET,
            domain_name=domain_name if domain_name is not None else UNSET,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    # --- SourceRevision endpoints ---

    async def post_source_revision(
        self,
        info_source_id: str,
        content_fingerprint: str,
        captured_at: datetime.datetime,
        *,
        source_revision_id: str | None = None,
        content_cache_uri: str | None = None,
        content_cache_expires_at: datetime.datetime | None = None,
        content_media_type: str | None = None,
        content_size_bytes: int | None = None,
    ) -> SourceRevisionOut:
        """Record a new SourceRevision (Watcher write path).

        ``source_revision_id`` may be pre-allocated by the caller so the
        scratch file at ``content_cache_uri`` can be written under its
        final filename before the POST round-trips. Idempotency on
        ``(info_source_id, content_fingerprint)`` still wins on re-POST —
        the server returns the existing row's id, which may differ from
        the client-supplied value. A supplied ULID that's already bound
        to a different (source, fingerprint) pair raises ``Conflict``.
        """
        body = SourceRevisionCreate(
            info_source_id=info_source_id,
            content_fingerprint=content_fingerprint,
            captured_at=captured_at,
            source_revision_id=(source_revision_id if source_revision_id is not None else UNSET),
            content_cache_uri=(content_cache_uri if content_cache_uri is not None else UNSET),
            content_cache_expires_at=(
                content_cache_expires_at if content_cache_expires_at is not None else UNSET
            ),
            content_media_type=(content_media_type if content_media_type is not None else UNSET),
            content_size_bytes=(content_size_bytes if content_size_bytes is not None else UNSET),
        )
        response = await _create_source_revision.asyncio_detailed(
            client=self._gen_client, body=body
        )
        return _unwrap(response)

    async def patch_source_revision_cache(
        self,
        source_revision_id: str,
        *,
        content_cache_uri: str | None = UNSET,
        content_cache_expires_at: datetime.datetime | None = UNSET,
    ) -> SourceRevisionOut:
        """Patch a SourceRevision's cache fields (Replicator callback).

        Pass ``None`` to explicitly clear a field. Omit to leave untouched (UNSET).
        """
        body = SourceRevisionCachePatch(
            content_cache_uri=content_cache_uri,
            content_cache_expires_at=content_cache_expires_at,
        )
        response = await _patch_source_revision.asyncio_detailed(
            client=self._gen_client, source_revision_id=source_revision_id, body=body
        )
        return _unwrap(response)

    # --- Authoring tools (/api/v1/tools/*) ---

    async def validate_source_spec(self, document: dict) -> _tools.ValidationResult:
        """Validate a SourceSpec document against the v1 JSON Schema."""
        return await _tools.validate_source_spec(self, document)

    async def validate_rep_spec(self, document: dict) -> _tools.ValidationResult:
        """Validate a RepSpec document against the v1 JSON Schema."""
        return await _tools.validate_rep_spec(self, document)

    async def validate_rep_fields(
        self, bag: dict, *, required_fields: list[str] | None = None
    ) -> _tools.ValidationResult:
        """Validate a rep_fields bag; optionally check required 'ns.key' paths."""
        return await _tools.validate_rep_fields(self, bag, required_fields=required_fields)

    async def resolve_rep_fields(self, bag: dict) -> dict[str, Any]:
        """Enrich a raw rep_fields bag with slug companions."""
        return await _tools.resolve_rep_fields(self, bag)

    async def find_info_item(self, query: str, *, limit: int = 20) -> list[InfoItemOut]:
        """Search Information Items by name + description (case-insensitive).

        Returns up to ``limit`` matches, newest first. Use before
        ``create_info_item`` to avoid duplicating an existing item.
        """
        return await _tools.find_info_item(self, query, limit=limit)

    async def fetch_and_render(
        self, url: str, *, render: bool = False
    ) -> _tools.FetchAndRenderResult:
        """Fetch a URL and return its body + headers.

        ``render=True`` raises (501) until the Playwright fetcher lands.
        Body bytes are truncated at 5 MiB; ``truncated`` flags the case.
        """
        return await _tools.fetch_and_render(self, url, render=render)

    async def preview_extraction(
        self, url: str, source_spec: dict
    ) -> _tools.PreviewExtractionResult:
        """Validate, fetch, extract, and fingerprint with a candidate SourceSpec.

        ``url`` is the URL to fetch. ``source_spec`` is the extraction spec
        (schema_version, extraction, fingerprint — no target section).
        """
        return await _tools.preview_extraction(self, url, source_spec)

    async def propose_selectors(
        self, url: str, description: str, *, top_k: int = 5
    ) -> list[_tools.SelectorCandidate]:
        """Suggest ranked CSS selector candidates for matching content.

        Empty match set returns ``[]``. Always pair with ``preview_extraction``
        to verify the chosen selector before persisting via ``create_info_item``.
        """
        return await _tools.propose_selectors(self, url, description, top_k=top_k)

    # --- Domain endpoints (v4.1+; typed returns since v4.2.0) ---

    async def list_domains(
        self,
        *,
        is_active: bool | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PageDomainOut:
        """List Domains as a paginated envelope.

        Pass ``is_active=True/False`` to filter by active status.
        Pass ``archived=True`` to restrict to archived domains.
        ``limit``/``offset`` are forwarded when set; omit to accept server
        defaults (limit=100, offset=0). Server caps ``limit`` at 500.
        """
        response = await _list_domains.asyncio_detailed(
            client=self._gen_client,
            is_active=is_active if is_active is not None else UNSET,
            archived=archived if archived is not None else UNSET,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    async def get_domain(self, name: str) -> DomainOut:
        """Fetch a single Domain by hostname."""
        response = await _get_domain.asyncio_detailed(client=self._gen_client, name=name)
        return _unwrap(response)

    async def upsert_domain(
        self,
        name: str,
        *,
        notes: str | None = None,
        is_active: bool | None = None,
        min_interval_seconds: float | None = None,
        default_watch_spec: dict | None = UNSET,
    ) -> DomainOut:
        """Create or update a Domain (upsert by hostname).

        ``None`` for ``notes``, ``is_active`` or ``min_interval_seconds`` omits
        the field (left untouched server-side), matching the pre-v4.2.0
        behavior. ``default_watch_spec`` is the exception, since it can be
        cleared: omit it to leave it untouched, pass ``None`` to clear it.

        ``is_active=False`` suspends the host: its items are announced
        ``active=false``. ``min_interval_seconds`` is the host's
        ``content.fetch-policy`` frame (#366); ``default_watch_spec`` is the
        domain tier of the announced cadence for items with no interval of
        their own (#364).
        """
        body = DomainPatch(
            notes=notes if notes is not None else UNSET,
            is_active=is_active if is_active is not None else UNSET,
            min_interval_seconds=(
                min_interval_seconds if min_interval_seconds is not None else UNSET
            ),
            default_watch_spec=(
                DomainPatchDefaultWatchSpecType0.from_dict(default_watch_spec)
                if isinstance(default_watch_spec, dict)
                else default_watch_spec
            ),
        )
        response = await _upsert_domain.asyncio_detailed(
            client=self._gen_client, name=name, body=body
        )
        return _unwrap(response)

    async def delete_domain(self, name: str) -> None:
        """Delete a Domain. Raises ``Conflict`` (409) while InfoSources or
        notification subscriptions reference it."""
        response = await _delete_domain.asyncio_detailed(client=self._gen_client, name=name)
        _unwrap_no_content(response)

    async def archive_domain(self, name: str) -> DomainOut:
        """Set archived_at on a Domain; suspends the host."""
        response = await _archive_domain.asyncio_detailed(client=self._gen_client, name=name)
        return _unwrap(response)

    async def restore_domain(self, name: str) -> DomainOut:
        """Clear archived_at on a Domain; resumes the host unless it is inactive."""
        response = await _restore_domain.asyncio_detailed(client=self._gen_client, name=name)
        return _unwrap(response)

    # --- Notification subscriptions (archiver#363; v5.16.0+) ---

    async def list_notification_subscriptions(
        self,
        *,
        scope: str | None = None,
        domain: str | None = None,
        info_item_id: str | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PageNotificationSubscriptionOut:
        """List subscriptions, oldest first, as a paginated envelope.

        ``scope`` is ``global``, ``domain`` or ``item``. ``domain`` (a hostname)
        and ``info_item_id`` select that host's or item's own scoped rows, not
        everything that would match. Server caps ``limit`` at 500.
        """
        response = await _list_subscriptions.asyncio_detailed(
            client=self._gen_client,
            scope=UNSET if scope is None else _SubscriptionScope(scope),
            domain=UNSET if domain is None else domain,
            info_item_id=UNSET if info_item_id is None else info_item_id,
            is_active=UNSET if is_active is None else is_active,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    async def get_notification_subscription(
        self, subscription_id: str
    ) -> NotificationSubscriptionOut:
        """One subscription. Raises ``NotFound``."""
        response = await _get_subscription.asyncio_detailed(
            client=self._gen_client, subscription_id=subscription_id
        )
        return _unwrap(response)

    async def create_notification_subscription(
        self, subscription: dict[str, Any]
    ) -> NotificationSubscriptionOut:
        """Create a subscription from a ``NotificationSubscriptionCreate`` body.

        ``title``, ``scope`` with exactly its ref (``domain``: a hostname with a
        Domain row; ``item``: ``info_item_id``), ``events``, ``remote_channel_id``,
        optional ``is_active``, ``content_config`` and ``imported_watcher_id``.
        The scope and ref are fixed after create. Raises ``ValidationError``
        (422, nothing stored) or ``Conflict`` (a duplicate ``imported_watcher_id``).
        Nothing sends.
        """
        response = await _create_subscription.asyncio_detailed(
            client=self._gen_client, body=NotificationSubscriptionCreate.from_dict(subscription)
        )
        return _unwrap(response)

    async def update_notification_subscription(
        self, subscription_id: str, changes: dict[str, Any]
    ) -> NotificationSubscriptionOut:
        """Change ``title``, ``events``, ``remote_channel_id``, ``is_active`` or
        ``content_config`` - only the keys in ``changes``. ``content_config`` is
        replaced whole; ``None`` returns it to all defaults. Raises ``NotFound``
        or ``ValidationError`` (including for any attempt to re-scope)."""
        response = await _update_subscription.asyncio_detailed(
            client=self._gen_client,
            subscription_id=subscription_id,
            body=NotificationSubscriptionPatch.from_dict(changes),
        )
        return _unwrap(response)

    async def delete_notification_subscription(self, subscription_id: str) -> None:
        """Delete a subscription. Raises ``NotFound``."""
        response = await _delete_subscription.asyncio_detailed(
            client=self._gen_client, subscription_id=subscription_id
        )
        _unwrap_no_content(response)


def _unwrap(response: Any) -> Any:
    """Return parsed body on 2xx; raise typed error otherwise.

    ``response`` is a generated ``Response[T]``; ``response.parsed`` is the
    typed body produced by the openapi-python-client output.
    """
    if 200 <= response.status_code < 300:
        return response.parsed
    raise error_from_response(int(response.status_code), response.content)


def _unwrap_no_content(response: Any) -> None:
    """Raise typed error on non-2xx; return None on 204."""
    if 200 <= response.status_code < 300:
        return None
    raise error_from_response(int(response.status_code), response.content)
