"""Pydantic IO schemas for top-level /rep-specs endpoints.

RepSpecs are *tiered*-mutable post-create (archiver#83): ``name`` is always
editable, ``document`` only while the RepSpec is a draft (no assignments), and
``provider`` never. There is no DELETE. See
docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RepSpecCreate(BaseModel):
    """Request body for POST /rep-specs.

    ``schema_version`` is server-defaulted to 1 — only v1 exists today, so
    accepting a client-supplied value would be ceremony. Bump the server
    default (and add a discriminator) once a v2 envelope ships.
    """

    model_config = {"extra": "forbid"}

    provider: str = Field(
        min_length=1,
        max_length=50,
        description="Provider key (e.g. 'gcs', 'gdrive', 'ia'). Validated via validate_rep_spec.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Operator-friendly label for this RepSpec. Not unique by design.",
    )
    document: dict[str, Any] = Field(
        description=(
            "RepSpec envelope document. Validated against rep_spec_schema/v1.json + "
            "the per-provider sub-schema at rep_spec_schema/providers/{provider}/v1.json."
        ),
    )


class RepSpecPatch(BaseModel):
    """Request body for PATCH /rep-specs/{rep_spec_id}.

    Both fields are optional; **omitting** a field leaves it untouched.
    Explicitly sending ``null`` is rejected rather than silently treated as
    omission: both columns are ``NOT NULL``, so ``null`` has no "clear this"
    meaning, and conflating the two would quietly swallow a malformed request.
    ``provider`` is absent by design — it is frozen for the life of the RepSpec,
    and supplying a ``document`` whose ``provider`` differs from the stored one
    is a 422.

    ``document`` is a whole-document *replacement*, not a merge patch: merge
    semantics cannot express key removal, which would make ``object_options``
    entries unremovable under the envelope's ``additionalProperties: false``.
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="New operator-friendly label. Editable regardless of assignment state.",
    )
    document: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Replacement RepSpec envelope document. Accepted only while the RepSpec "
            "is a draft (zero assignment rows, active or deactivated); otherwise 409. "
            "Validated exactly as on create."
        ),
    )

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "RepSpecPatch":
        """Distinguish an omitted field from one explicitly set to ``null``.

        ``model_fields_set`` is the only way to tell them apart once both have
        landed as ``None``. Neither column is nullable, so an explicit ``null``
        is a client error, not a no-op.
        """
        nulled = sorted(
            name
            for name in ("name", "document")
            if name in self.model_fields_set and getattr(self, name) is None
        )
        if nulled:
            raise ValueError(
                f"{', '.join(nulled)}: null is not accepted; omit the field to leave it unchanged"
            )
        return self


class RepSpecOut(BaseModel):
    """Projection of a rep_specs row."""

    rep_spec_id: str = Field(description="ULID identifying this RepSpec.")
    provider: str = Field(description="Provider key (e.g. 'gcs', 'gdrive', 'ia').")
    name: str = Field(description="Operator-friendly label for this RepSpec.")
    schema_version: int = Field(
        description="RepSpec envelope schema version; always 1 in the current implementation."
    )
    document: dict[str, Any] = Field(
        description=(
            "RepSpec envelope document validated against rep_spec_schema/v1.json "
            "and the per-provider sub-schema."
        )
    )
    created_at: datetime = Field(description="UTC timestamp when the RepSpec was created.")
    updated_at: datetime | None = Field(
        description=(
            "UTC timestamp of the last edit, or null if the RepSpec has never been "
            "edited. Never backfilled from created_at. Always present in responses "
            "(required, nullable) — matching the other nullable projections."
        ),
    )
