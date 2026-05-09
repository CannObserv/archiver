"""create_info_source — author a new InfoSource (root or fragment).

Shared helper used by both ``POST /info-sources`` (top-level) and the
atomic ``POST /info-items`` flow (initial primary source). Centralizing here
keeps URL canonicalization, validation, and the root/fragment XOR check in
lockstep across both entry points.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoSource
from src.core.source_spec_schema.validator import (
    ValidationError,
    validate_fragment_source_spec,
    validate_root_source_spec,
)
from src.core.url_canonicalization import canonicalize_url


class CreateInfoSourceError(Exception):
    """Base class for create_info_source failures."""


class InvalidSourceSpecError(CreateInfoSourceError):
    """The submitted source_spec failed schema or shape validation."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"invalid source_spec: {errors}")


class ParentNotFoundError(CreateInfoSourceError):
    """The given parent_info_source_id does not exist."""


class ParentMustBeRootError(CreateInfoSourceError):
    """A fragment's parent must itself be a root (no fragment-of-fragment chains)."""


class DuplicateUrlError(CreateInfoSourceError):
    """Another InfoSource with the same canonicalized URL already exists."""

    def __init__(self, *, existing_info_source_id: ULID, url: str) -> None:
        self.existing_info_source_id = existing_info_source_id
        self.url = url
        super().__init__(f"duplicate url: {url} (existing id={existing_info_source_id})")


async def create_info_source(
    db: AsyncSession,
    *,
    source_spec: dict,
    parent_info_source_id: ULID | None = None,
) -> InfoSource:
    """Persist a new InfoSource and return the row.

    Validates the source_spec shape (root vs. fragment), looks up the parent
    (when supplied) and rejects fragment-of-fragment chains, applies URL
    canonicalization for roots, and surfaces duplicate-URL collisions as a
    typed error before they reach the database.

    Caller is responsible for committing the session.
    """
    if parent_info_source_id is None:
        ok, errors = validate_root_source_spec(source_spec)
        if not ok:
            raise InvalidSourceSpecError(errors)
    else:
        ok, errors = validate_fragment_source_spec(source_spec)
        if not ok:
            raise InvalidSourceSpecError(errors)

        parent = await db.get(InfoSource, parent_info_source_id)
        if parent is None:
            raise ParentNotFoundError(str(parent_info_source_id))
        if parent.parent_info_source_id is not None:
            raise ParentMustBeRootError(str(parent_info_source_id))

    spec_doc: dict = dict(source_spec)

    if parent_info_source_id is None:
        target = dict(spec_doc.get("target", {}))
        raw_url: str = target["url"]
        strip_keys: list[str] = target.get("url_canonicalization", {}).get("strip_query_keys") or []
        canonical = canonicalize_url(raw_url, strip_query_keys=strip_keys or None)
        target["url"] = canonical
        spec_doc["target"] = target

        existing = (
            await db.execute(select(InfoSource).where(InfoSource.url == canonical))
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateUrlError(
                existing_info_source_id=existing.info_source_id,
                url=canonical,
            )

    src = InfoSource(
        source_spec=spec_doc,
        schema_version=spec_doc.get("schema_version", 1),
        parent_info_source_id=parent_info_source_id,
    )
    db.add(src)
    await db.flush()
    return src
