"""Typed Pydantic models for change-bus event payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InfoItemBinding(BaseModel):
    """One active InfoItem↔InfoSource binding at the moment a revision was captured."""

    model_config = ConfigDict(extra="forbid")

    info_item_id: str
    role: str | None  # None = primary (root); 'cross_check' or 'sub_aspect' = fragment


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
