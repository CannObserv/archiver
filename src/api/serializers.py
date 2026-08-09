"""ORM → Pydantic ``Out`` serialisers shared across route modules.

Lifted out of route files when more than one route module needs the same
mapping (e.g. ``tools.find-info-items`` reuses ``info-items``' serialiser).
"""

from src.api.schemas.info_item import (
    InfoItemOut,
    InfoItemRepSpecOut,
    InfoItemSourceOut,
)
from src.api.schemas.info_source import InfoSourceOut
from src.api.schemas.rep_spec import RepSpecOut
from src.api.schemas.source_revision import SourceRevisionOut
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    RepSpec,
    SourceRevision,
)


def info_item_source_to_out(src: InfoItemSource) -> InfoItemSourceOut:
    """Serialise an InfoItemSource ORM row."""
    return InfoItemSourceOut(
        info_source_id=str(src.info_source_id),
        is_active=src.deactivated_at is None,
        created_at=src.created_at,
        deactivated_at=src.deactivated_at,
    )


def info_item_rep_spec_to_out(airs: InfoItemRepSpec) -> InfoItemRepSpecOut:
    """Serialise an InfoItemRepSpec ORM row."""
    return InfoItemRepSpecOut(
        id=str(airs.id),
        rep_spec_id=str(airs.rep_spec_id),
        activated_at=airs.activated_at,
        deactivated_at=airs.deactivated_at,
        public_url=airs.public_url,
    )


def info_source_to_out(src: InfoSource) -> InfoSourceOut:
    """Serialise an InfoSource ORM row."""
    return InfoSourceOut(
        info_source_id=str(src.info_source_id),
        url=src.url,
        source_specs=src.source_specs,
        domain_name=src.domain_name,
        created_at=src.created_at,
    )


def source_revision_to_out(rev: SourceRevision) -> SourceRevisionOut:
    """Serialise a SourceRevision ORM row."""
    return SourceRevisionOut(
        source_revision_id=str(rev.source_revision_id),
        info_source_id=str(rev.info_source_id),
        content_fingerprint=rev.content_fingerprint,
        captured_at=rev.captured_at,
        content_size_bytes=rev.content_size_bytes,
        content_media_type=rev.content_media_type,
        content_cache_uri=rev.content_cache_uri,
        content_cache_expires_at=rev.content_cache_expires_at,
        source_media_type=rev.source_media_type,
        spec_fingerprint=rev.spec_fingerprint,
        command_id=rev.command_id,
    )


def rep_spec_to_out(spec: RepSpec) -> RepSpecOut:
    """Serialise a RepSpec ORM row."""
    return RepSpecOut(
        rep_spec_id=str(spec.rep_spec_id),
        provider=spec.provider,
        name=spec.name,
        schema_version=spec.schema_version,
        document=spec.document,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )


def info_item_to_out(
    item: InfoItem,
    sources: list[InfoItemSource] | None = None,
    rep_specs: list[InfoItemRepSpec] | None = None,
    base_url: str | None = None,
) -> InfoItemOut:
    """Serialise an InfoItem ORM row with optional related rows."""
    item_id = str(item.info_item_id)
    dashboard_url = f"{base_url.rstrip('/')}/info-items/{item_id}" if base_url else None
    return InfoItemOut(
        info_item_id=item_id,
        name=item.name,
        description=item.description,
        owner=item.owner,
        rep_fields=item.rep_fields or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
        info_item_sources=[info_item_source_to_out(s) for s in (sources or [])],
        info_item_rep_specs=[info_item_rep_spec_to_out(r) for r in (rep_specs or [])],
        dashboard_url=dashboard_url,
    )
