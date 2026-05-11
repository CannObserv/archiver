"""create_rep_spec — author a new RepSpec row.

Validates the envelope + provider sub-schema, enforces that the request-level
``provider`` matches the embedded document's provider, and persists the row at
schema_version=1. Caller is responsible for committing the session.

RepSpecs are immutable once written; there is no update or delete path. To
evolve provider config, author a new RepSpec and reassign affected InfoItems.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import RepSpec
from src.core.rep_spec_schema.validator import ValidationError, validate_rep_spec

# Pinned to the envelope at src/core/rep_spec_schema/v1.json. When a v2.json
# envelope ships, bump both in lockstep — the validator selects the envelope
# by filename, but doesn't expose a version constant we can import.
CURRENT_SCHEMA_VERSION = 1


class CreateRepSpecError(Exception):
    """Base class for create_rep_spec failures."""


class InvalidRepSpecError(CreateRepSpecError):
    """The submitted document failed envelope or provider sub-schema validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid rep_spec: {errors}")


async def create_rep_spec(
    db: AsyncSession,
    *,
    provider: str,
    name: str,
    document: dict,
) -> RepSpec:
    """Persist a new RepSpec row and return it.

    The document is validated against the v1 envelope and the per-provider
    sub-schema. If ``document['provider']`` disagrees with the request-level
    ``provider`` argument, the call is rejected — the two are redundant by
    design, and storing a disagreement would corrupt the index.
    """
    errors: list[ValidationError] = []

    doc_provider = document.get("provider")
    if doc_provider is not None and doc_provider != provider:
        errors.append(
            {
                "path": "/provider",
                "message": (
                    f"request provider {provider!r} disagrees with "
                    f"document.provider {doc_provider!r}"
                ),
            }
        )

    ok, schema_errors = validate_rep_spec(document)
    if not ok:
        errors.extend(schema_errors)

    if errors:
        raise InvalidRepSpecError(errors)

    spec = RepSpec(
        provider=provider,
        name=name,
        schema_version=CURRENT_SCHEMA_VERSION,
        document=document,
    )
    db.add(spec)
    await db.flush()
    return spec
