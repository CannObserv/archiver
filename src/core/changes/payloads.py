"""Typed Pydantic models for change-bus event payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InfoItemBinding(BaseModel):
    """One active InfoItem↔InfoSource binding at the moment a revision was captured."""

    model_config = ConfigDict(extra="forbid")

    info_item_id: str
    role: str | None  # None = primary (root); 'cross_check' = fragment


class SourceRevisionCapturedEvent(BaseModel):
    """Event emitted when a new SourceRevision is recorded for an InfoSource.

    Producer: Archiver (POST /source-revisions on insert; not on idempotent no-op).
    Subscribers: Replicator, Notifier, etc. — consumers filter on
    ``bindings[*].role`` per their semantics (e.g. Replicator typically
    cares only about ``role IS NULL``; selector-rot tooling cares about
    ``role == 'cross_check'``).

    ``schema_version`` is the wire-format version for this event type. Bump it
    only on incompatible reshapes (field removal, type change, semantic
    redefinition). Additive fields do not require a bump — consumers must
    parse with extra-field tolerance per the convention in AGENTS.md.

    Producer keeps ``extra="forbid"`` to catch typos at emit time; consumer
    mirrors switch to ``extra="ignore"`` per AGENTS.md so additive producer
    fields do not raise ``ValidationError``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    event_type: Literal["source_revision_captured"] = "source_revision_captured"
    occurred_at: datetime
    info_source_id: str
    source_revision_id: str
    content_fingerprint: str
    bindings: list[InfoItemBinding]


class InfoItemPrimaryChangedEvent(BaseModel):
    """Event emitted when an InfoItem's current primary InfoSource changes.

    Fired by ``POST /info-items/{id}/info-sources`` whenever a NULL-role
    binding is successfully created. Subscribers (Watcher, Replicator, etc.)
    use this to discover URL succession — start watching the new primary,
    and optionally continue watching the old one.

    ``old_info_source_id`` is ``None`` when this is the first primary assignment
    for the InfoItem (no prior primary existed). Consumers should branch on
    ``None`` vs. a non-null string.

    ``schema_version`` follows the same bump convention as
    ``SourceRevisionCapturedEvent``: additive fields do not require a bump;
    consumer-side mirrors use ``extra="ignore"``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    event_type: Literal["info_item_primary_changed"] = "info_item_primary_changed"
    occurred_at: datetime
    info_item_id: str
    old_info_source_id: str | None  # None = first primary assignment
    new_info_source_id: str
