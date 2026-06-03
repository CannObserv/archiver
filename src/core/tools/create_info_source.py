"""create_info_source — author a new InfoSource.

Shared helper used by ``POST /info-sources`` and the atomic ``POST /info-items`` flow.
Centralizes URL canonicalization, spec validation, and content-kind family enforcement.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import InfoSource
from src.core.source_spec_schema.families import family_for
from src.core.source_spec_schema.validator import ValidationError, validate_source_spec
from src.core.url_canonicalization import canonicalize_url


class CreateInfoSourceError(Exception):
    """Base class for create_info_source failures."""


class InvalidUrlError(CreateInfoSourceError):
    """The submitted URL failed canonicalization (no scheme or host)."""


class InvalidSourceSpecError(CreateInfoSourceError):
    """One or more specs in source_specs failed schema validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid source_spec: {errors}")


class MixedAlgorithmFamilyError(CreateInfoSourceError):
    """The source_specs list contains algorithms from different content-kind families.

    All specs must use the same family (html_text: css/xpath/regex/full_page;
    json: jsonpath) because they are evaluated against the same fetched bytes.
    """


async def create_info_source(
    db: AsyncSession,
    *,
    url: str,
    source_specs: list[dict],
) -> InfoSource:
    """Persist a new InfoSource and return the row.

    Canonicalizes the URL, validates each spec, enforces same-family constraint,
    then inserts. Caller commits.
    """
    # 1. Canonicalize URL
    try:
        canonical_url = canonicalize_url(url)
    except ValueError as e:
        raise InvalidUrlError(str(e)) from e

    # 2. Validate specs list is non-empty
    if not source_specs:
        raise InvalidSourceSpecError(
            [{"path": "/source_specs", "message": "at least one spec is required"}]
        )

    # 3. Validate each spec element
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

    # 4. Enforce same content-kind family across all specs
    families = {family_for(spec["extraction"]["algorithm"]) for spec in source_specs}
    if len(families) > 1:
        raise MixedAlgorithmFamilyError(
            f"source_specs mix content-kind families: {families!r}. "
            "All specs must use the same family (html_text or json)."
        )

    src = InfoSource(url=canonical_url, source_specs=list(source_specs))
    db.add(src)
    await db.flush()
    return src
