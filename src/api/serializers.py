"""ORM → Pydantic ``Out`` serialisers shared across route modules.

Lifted out of route files when more than one route module needs the same
mapping (e.g. ``tools.find-info-items`` reuses ``info-items``' serialiser).
"""

from src.api.schemas.info_item import (
    InfoItemOut,
    InfoItemRepSpecOut,
    InfoItemSourceOut,
)
from src.core.models import InfoItem, InfoItemRepSpec, InfoItemSource


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


# ---------------------------------------------------------------------------
# Legacy serialiser — kept for info_specs.py (B11 will remove this).
# Importing InfoSpec only when called so that a missing model does not break
# application startup when info_specs routes are still present.
# ---------------------------------------------------------------------------


def info_spec_to_out(spec):  # type: ignore[no-untyped-def]
    """Serialise an InfoSpec ORM row (legacy; removed in B11)."""
    from src.api.schemas.info_spec import InfoSpecOut  # noqa: PLC0415

    return InfoSpecOut(
        info_spec_id=str(spec.info_spec_id),
        info_item_id=str(spec.info_item_id),
        schema_version=spec.schema_version,
        document=spec.document,
        priority=spec.priority,
        active=spec.active,
        created_at=spec.created_at,
    )
