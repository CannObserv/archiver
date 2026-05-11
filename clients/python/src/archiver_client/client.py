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
from archiver_client.generated.api.info_items import (
    add_info_source_api_v1_info_items_info_item_id_info_sources_post as _add_info_source,
)
from archiver_client.generated.api.info_items import (
    add_rep_spec_assignment_api_v1_info_items_info_item_id_rep_spec_assignments_post as _add_rep_spec,
)
from archiver_client.generated.api.info_items import (
    bind_source_revision_api_v1_info_items_info_item_id_source_revisions_post as _bind_revision,
)
from archiver_client.generated.api.info_items import (
    create_info_item_api_v1_info_items_post as _create_info_item,
)
from archiver_client.generated.api.info_items import (
    deactivate_rep_spec_assignment_api_v1_info_items_info_item_id_rep_spec_assignments_assignment_id_delete as _deactivate_rep_spec,
)
from archiver_client.generated.api.info_items import (
    get_info_item_api_v1_info_items_info_item_id_get as _get_info_item,
)
from archiver_client.generated.api.info_items import (
    list_info_items_api_v1_info_items_get as _list_info_items,
)
from archiver_client.generated.api.info_items import (
    patch_rep_spec_assignment_public_url_api_v1_info_items_info_item_id_rep_spec_assignments_assignment_id_patch as _patch_rep_spec_url,
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
from archiver_client.generated.api.rep_specs import (
    create_rep_spec_route_api_v1_rep_specs_post as _create_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    get_rep_spec_api_v1_rep_specs_rep_spec_id_get as _get_rep_spec,
)
from archiver_client.generated.api.rep_specs import (
    list_rep_specs_api_v1_rep_specs_get as _list_rep_specs,
)
from archiver_client.generated.api.source_revisions import (
    create_source_revision_api_v1_source_revisions_post as _create_source_revision,
)
from archiver_client.generated.api.source_revisions import (
    patch_source_revision_api_v1_source_revisions_source_revision_id_patch as _patch_source_revision,
)
from archiver_client.generated.client import AuthenticatedClient
from archiver_client.generated.models.info_item_create import InfoItemCreate
from archiver_client.generated.models.info_item_create_initial_source_spec_type_0 import (
    InfoItemCreateInitialSourceSpecType0,
)
from archiver_client.generated.models.info_item_create_rep_fields import InfoItemCreateRepFields
from archiver_client.generated.models.info_item_out import InfoItemOut
from archiver_client.generated.models.info_item_rep_spec_create import InfoItemRepSpecCreate
from archiver_client.generated.models.info_item_rep_spec_out import InfoItemRepSpecOut
from archiver_client.generated.models.info_item_rep_spec_public_url_patch import (
    InfoItemRepSpecPublicUrlPatch,
)
from archiver_client.generated.models.info_item_source_create import InfoItemSourceCreate
from archiver_client.generated.models.info_item_source_out import InfoItemSourceOut
from archiver_client.generated.models.info_item_source_revision_create import (
    InfoItemSourceRevisionCreate,
)
from archiver_client.generated.models.info_item_source_revision_out import (
    InfoItemSourceRevisionOut,
)
from archiver_client.generated.models.info_source_create import InfoSourceCreate
from archiver_client.generated.models.info_source_create_source_spec import (
    InfoSourceCreateSourceSpec,
)
from archiver_client.generated.models.info_source_out import InfoSourceOut
from archiver_client.generated.models.page_info_item_out import PageInfoItemOut
from archiver_client.generated.models.page_info_source_out import PageInfoSourceOut
from archiver_client.generated.models.page_rep_spec_out import PageRepSpecOut
from archiver_client.generated.models.rep_spec_create import RepSpecCreate
from archiver_client.generated.models.rep_spec_create_document import RepSpecCreateDocument
from archiver_client.generated.models.rep_spec_out import RepSpecOut
from archiver_client.generated.models.rep_spec_assignment_create import RepSpecAssignmentCreate
from archiver_client.generated.models.source_revision_cache_patch import SourceRevisionCachePatch
from archiver_client.generated.models.source_revision_create import SourceRevisionCreate
from archiver_client.generated.models.source_revision_out import SourceRevisionOut
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
        initial_source_spec: dict | None = None,
        initial_rep_spec_assignments: list[dict] | None = None,
    ) -> InfoItemOut:
        """Create a new InfoItem.

        ``initial_source_spec`` atomically creates a primary InfoSource alongside
        the InfoItem. ``initial_rep_spec_assignments`` atomically creates
        RepSpec assignment rows. On validation failure, no rows are persisted.
        """
        body = InfoItemCreate(name=name, description=description, owner=owner)
        if rep_fields is not None:
            body.rep_fields = InfoItemCreateRepFields.from_dict(rep_fields)
        if initial_source_spec is not None:
            body.initial_source_spec = InfoItemCreateInitialSourceSpecType0.from_dict(
                initial_source_spec
            )
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
    ) -> PageInfoItemOut:
        """List InfoItems as a paginated envelope.

        ``limit`` and ``offset`` are forwarded to the server when set; omit to
        accept server defaults (limit=100, offset=0). Server caps ``limit`` at
        500. The returned ``PageInfoItemOut`` carries ``items``, ``has_more``,
        ``limit``, and ``offset``.
        """
        response = await _list_info_items.asyncio_detailed(
            client=self._gen_client,
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    async def get_info_item(self, info_item_id: str) -> InfoItemOut:
        """Fetch a single InfoItem by ID."""
        response = await _get_info_item.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id
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

        ``activated_at`` defaults to now() when omitted.
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
        self, info_item_id: str, info_source_id: str, role: str
    ) -> InfoItemSourceOut:
        """Declare an InfoItem → InfoSource binding with the given role."""
        body = InfoItemSourceCreate(info_source_id=info_source_id, role=role)
        response = await _add_info_source.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    # --- Top-level InfoSource endpoints ---

    async def create_info_source(
        self,
        source_spec: dict,
        *,
        parent_info_source_id: str | None = None,
    ) -> InfoSourceOut:
        """Author a new InfoSource (root or fragment).

        Pass ``parent_info_source_id`` to create a fragment under a root
        InfoSource. Without it, the source is created as a root and
        ``source_spec`` must carry ``target.url``.
        """
        body = InfoSourceCreate(
            source_spec=InfoSourceCreateSourceSpec.from_dict(source_spec),
            parent_info_source_id=(
                parent_info_source_id if parent_info_source_id is not None else UNSET
            ),
        )
        response = await _create_info_source.asyncio_detailed(client=self._gen_client, body=body)
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
        parent_info_source_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> PageInfoSourceOut:
        """List InfoSources as a paginated envelope.

        With ``parent_info_source_id`` set, restricts to fragments under that
        parent. ``limit``/``offset`` are forwarded when set; omit to accept
        server defaults (limit=100, offset=0). Server caps ``limit`` at 500.
        """
        response = await _list_info_sources.asyncio_detailed(
            client=self._gen_client,
            parent_info_source_id=(
                parent_info_source_id if parent_info_source_id is not None else UNSET
            ),
            limit=UNSET if limit is None else limit,
            offset=UNSET if offset is None else offset,
        )
        return _unwrap(response)

    # --- SourceRevision binding ---

    async def bind_revision(
        self,
        info_item_id: str,
        source_revision_id: str,
        *,
        bound_at: datetime.datetime | None = None,
    ) -> InfoItemSourceRevisionOut:
        """Bind a SourceRevision to an InfoItem (declares it as the latest known content)."""
        body = InfoItemSourceRevisionCreate(
            source_revision_id=source_revision_id,
            bound_at=bound_at if bound_at is not None else UNSET,
        )
        response = await _bind_revision.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)

    # --- SourceRevision endpoints ---

    async def post_source_revision(
        self,
        info_source_id: str,
        content_fingerprint: str,
        captured_at: datetime.datetime,
        *,
        content_cache_uri: str | None = None,
        content_cache_expires_at: datetime.datetime | None = None,
        content_media_type: str | None = None,
        content_size_bytes: int | None = None,
    ) -> SourceRevisionOut:
        """Record a new SourceRevision (Watcher write path)."""
        body = SourceRevisionCreate(
            info_source_id=info_source_id,
            content_fingerprint=content_fingerprint,
            captured_at=captured_at,
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

    async def preview_extraction(self, source_spec: dict) -> _tools.PreviewExtractionResult:
        """Validate, fetch, extract, and fingerprint with a candidate SourceSpec.

        Accepts a SourceSpec document dict (v2 shape). Use after authoring the
        SourceSpec to verify extracted chunks before persisting.
        """
        return await _tools.preview_extraction(self, source_spec)

    async def propose_selectors(
        self, url: str, description: str, *, top_k: int = 5
    ) -> list[_tools.SelectorCandidate]:
        """Suggest ranked CSS selector candidates for matching content.

        Empty match set returns ``[]``. Always pair with ``preview_extraction``
        to verify the chosen selector before persisting via ``create_info_item``.
        """
        return await _tools.propose_selectors(self, url, description, top_k=top_k)


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
