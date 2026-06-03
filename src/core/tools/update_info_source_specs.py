"""update_info_source_specs — replace source_specs on an existing InfoSource."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoSource
from src.core.source_spec_schema.families import family_for
from src.core.source_spec_schema.validator import ValidationError, validate_source_spec


class UpdateInfoSourceSpecsError(Exception):
    """Base class for update_info_source_specs failures."""


class InfoSourceNotFoundError(UpdateInfoSourceSpecsError):
    """The given info_source_id does not reference an InfoSource."""


class InvalidSourceSpecError(UpdateInfoSourceSpecsError):
    """One or more specs in the replacement list failed schema validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid source_spec: {errors}")


class MixedAlgorithmFamilyError(UpdateInfoSourceSpecsError):
    """The replacement source_specs list contains algorithms from different families."""


async def update_info_source_specs(
    db: AsyncSession,
    *,
    info_source_id: ULID,
    source_specs: list[dict],
) -> InfoSource:
    """Replace the source_specs list on an InfoSource. URL is immutable.

    Validates each spec and enforces same-family constraint. Caller commits.
    """
    src = await db.get(InfoSource, info_source_id)
    if src is None:
        raise InfoSourceNotFoundError(str(info_source_id))

    if not source_specs:
        raise InvalidSourceSpecError(
            [{"path": "/source_specs", "message": "at least one spec is required"}]
        )

    all_errors: list[ValidationError] = []
    for i, spec in enumerate(source_specs):
        ok, errs = validate_source_spec(spec)
        if not ok:
            for err in errs:
                all_errors.append(
                    {"path": f"/source_specs/{i}{err['path']}", "message": err["message"]}
                )
    if all_errors:
        raise InvalidSourceSpecError(all_errors)

    families = {family_for(spec["extraction"]["algorithm"]) for spec in source_specs}
    if len(families) > 1:
        raise MixedAlgorithmFamilyError(f"source_specs mix content-kind families: {families!r}")

    src.source_specs = list(source_specs)
    await db.flush()
    return src
