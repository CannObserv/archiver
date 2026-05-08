"""ORM → Pydantic ``Out`` serialisers shared across route modules.

Lifted out of route files when more than one route module needs the same
mapping (e.g. ``tools.find-info-items`` reuses ``info-items``' serialiser).
"""

from src.api.schemas.info_item import (
    InfoItemOut,
    InfoItemRepSpecOut,
    InfoItemSourceOut,
    InfoItemSourceRevisionOut,  # noqa: F401  (re-exported for route modules)
)
from src.core.models import InfoItem, InfoItemRepSpec, InfoItemSource, InfoItemSourceRevision


def info_item_source_to_out(src: InfoItemSource) -> InfoItemSourceOut:
    """Serialise an InfoItemSource ORM row."""
    return InfoItemSourceOut(
        info_source_id=str(src.info_source_id),
        role=src.role,
        created_at=src.created_at,
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


def info_item_source_revision_to_out(
    binding: InfoItemSourceRevision,
) -> InfoItemSourceRevisionOut:
    """Serialise an InfoItemSourceRevision ORM row."""
    return InfoItemSourceRevisionOut(
        info_item_id=str(binding.info_item_id),
        source_revision_id=str(binding.source_revision_id),
        bound_at=binding.bound_at,
    )


def info_item_to_out(
    item: InfoItem,
    sources: list[InfoItemSource] | None = None,
    rep_specs: list[InfoItemRepSpec] | None = None,
) -> InfoItemOut:
    """Serialise an InfoItem ORM row with optional related rows."""
    return InfoItemOut(
        info_item_id=str(item.info_item_id),
        name=item.name,
        description=item.description,
        owner=item.owner,
        rep_fields=item.rep_fields or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
        info_item_sources=[info_item_source_to_out(s) for s in (sources or [])],
        info_item_rep_specs=[info_item_rep_spec_to_out(r) for r in (rep_specs or [])],
    )

