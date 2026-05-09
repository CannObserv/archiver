"""Tests for create_info_source — InfoSource authoring helper.

Covers root + fragment shapes, validation, parent existence, parent-must-be-root,
URL canonicalization, and duplicate-URL handling.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from ulid import ULID

from src.core.models import InfoSource
from src.core.tools.create_info_source import (
    CreateInfoSourceError,
    DuplicateUrlError,
    InvalidSourceSpecError,
    ParentMustBeRootError,
    ParentNotFoundError,
    create_info_source,
)


def _root_doc(url: str = "https://example.com/p", **extra) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url, **(extra.pop("target_extra", {}))},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        **extra,
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_root_persists_with_canonicalized_url(session):
    """Host is lowercased; #fragment dropped (canonicalize_url contract)."""
    src = await create_info_source(
        session,
        source_spec=_root_doc("https://Example.COM/p#frag"),
    )

    assert src.parent_info_source_id is None
    assert src.url == "https://example.com/p"
    assert src.schema_version == 1


@pytest.mark.asyncio
async def test_create_fragment_persists_with_parent(session):
    parent = await create_info_source(session, source_spec=_root_doc())

    frag = await create_info_source(
        session,
        source_spec=_fragment_doc(),
        parent_info_source_id=parent.info_source_id,
    )

    assert frag.parent_info_source_id == parent.info_source_id
    assert frag.url is None


@pytest.mark.asyncio
async def test_strip_query_keys_honored(session):
    doc = _root_doc("https://example.com/p?utm_source=x&keep=1")
    doc["target"]["url_canonicalization"] = {"strip_query_keys": ["utm_source"]}

    src = await create_info_source(session, source_spec=doc)

    assert src.url == "https://example.com/p?keep=1"


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_without_url_rejected(session):
    """A root source with no target.url is rejected with structured errors."""
    bad = _fragment_doc()  # no target block

    with pytest.raises(InvalidSourceSpecError) as exc_info:
        await create_info_source(session, source_spec=bad)

    assert any(e["path"] == "/target/url" for e in exc_info.value.errors)


@pytest.mark.asyncio
async def test_fragment_with_target_url_rejected(session):
    """A fragment source must not carry target.url."""
    parent = await create_info_source(session, source_spec=_root_doc())
    bad = _root_doc("https://example.com/q")

    with pytest.raises(InvalidSourceSpecError) as exc_info:
        await create_info_source(
            session,
            source_spec=bad,
            parent_info_source_id=parent.info_source_id,
        )

    assert any(e["path"] == "/target/url" for e in exc_info.value.errors)


@pytest.mark.asyncio
async def test_schema_violation_rejected(session):
    """Bare schema-shape failures bubble up as InvalidSourceSpecError."""
    bad = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}

    with pytest.raises(InvalidSourceSpecError):
        await create_info_source(session, source_spec=bad)


# ---------------------------------------------------------------------------
# Parent semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_not_found_raises(session):
    with pytest.raises(ParentNotFoundError):
        await create_info_source(
            session,
            source_spec=_fragment_doc(),
            parent_info_source_id=ULID(),
        )


@pytest.mark.asyncio
async def test_parent_must_be_root(session):
    """Fragment-of-fragment chains are rejected."""
    root = await create_info_source(session, source_spec=_root_doc())
    frag1 = await create_info_source(
        session,
        source_spec=_fragment_doc(),
        parent_info_source_id=root.info_source_id,
    )

    with pytest.raises(ParentMustBeRootError):
        await create_info_source(
            session,
            source_spec=_fragment_doc(),
            parent_info_source_id=frag1.info_source_id,
        )


# ---------------------------------------------------------------------------
# Duplicate-URL handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_root_url_raises(session):
    """Two roots at the same canonicalized URL → DuplicateUrlError carrying existing id."""
    first = await create_info_source(session, source_spec=_root_doc())

    with pytest.raises(DuplicateUrlError) as exc_info:
        await create_info_source(session, source_spec=_root_doc())

    assert exc_info.value.existing_info_source_id == first.info_source_id
    assert exc_info.value.url == first.url


@pytest.mark.asyncio
async def test_duplicate_detection_uses_canonicalized_url(session):
    """Distinct raw URLs that canonicalize to the same value collide."""
    await create_info_source(session, source_spec=_root_doc("https://example.com/p"))

    with pytest.raises(DuplicateUrlError):
        await create_info_source(session, source_spec=_root_doc("https://EXAMPLE.com/p#frag"))


# ---------------------------------------------------------------------------
# Inheritance / shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_info_source_error_is_base_class():
    assert issubclass(InvalidSourceSpecError, CreateInfoSourceError)
    assert issubclass(ParentNotFoundError, CreateInfoSourceError)
    assert issubclass(ParentMustBeRootError, CreateInfoSourceError)
    assert issubclass(DuplicateUrlError, CreateInfoSourceError)


@pytest.mark.asyncio
async def test_db_round_trip(session):
    """Confirms the row is actually persisted to the InfoSource table."""
    src = await create_info_source(session, source_spec=_root_doc("https://example.com/x"))
    await session.flush()

    fetched = (
        await session.execute(
            select(InfoSource).where(InfoSource.info_source_id == src.info_source_id)
        )
    ).scalar_one()
    assert fetched.url == "https://example.com/x"
