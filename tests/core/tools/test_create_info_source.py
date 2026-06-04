"""Tests for create_info_source — InfoSource authoring helper."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.core.models import InfoSource
from src.core.tools.create_info_source import (
    CreateInfoSourceError,
    InvalidSourceSpecError,
    InvalidUrlError,
    MixedAlgorithmFamilyError,
    create_info_source,
)


def _spec(algorithm: str = "full_page", selector: str | None = None) -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if selector is not None:
        doc["extraction"]["selector"] = selector
    elif algorithm != "full_page":
        doc["extraction"]["selector"] = "#x"
    return doc


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_persists_with_canonicalized_url(session):
    """Host is lowercased; #fragment dropped."""
    src = await create_info_source(
        session,
        url="https://Example.COM/p#frag",
        source_specs=[_spec()],
    )
    assert src.url == "https://example.com/p"
    assert src.source_specs == [_spec()]


@pytest.mark.asyncio
async def test_create_with_multiple_specs(session):
    specs = [_spec("full_page"), _spec("css")]
    src = await create_info_source(session, url="https://example.com/p", source_specs=specs)
    assert src.source_specs == specs


@pytest.mark.asyncio
async def test_same_url_allowed_for_different_specs(session):
    """Multiple InfoSources with the same URL are valid."""
    a = await create_info_source(
        session, url="https://example.com/p", source_specs=[_spec("full_page")]
    )
    b = await create_info_source(session, url="https://example.com/p", source_specs=[_spec("css")])
    assert a.info_source_id != b.info_source_id
    assert a.url == b.url


@pytest.mark.asyncio
async def test_db_round_trip(session):
    src = await create_info_source(session, url="https://example.com/x", source_specs=[_spec()])
    await session.flush()
    fetched = (
        await session.execute(
            select(InfoSource).where(InfoSource.info_source_id == src.info_source_id)
        )
    ).scalar_one()
    assert fetched.url == "https://example.com/x"


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_url_raises(session):
    with pytest.raises(InvalidUrlError):
        await create_info_source(session, url="not-a-url", source_specs=[_spec()])


@pytest.mark.asyncio
async def test_empty_source_specs_rejected(session):
    with pytest.raises(InvalidSourceSpecError):
        await create_info_source(session, url="https://example.com/p", source_specs=[])


@pytest.mark.asyncio
async def test_invalid_spec_element_rejected(session):
    bad_spec = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}
    with pytest.raises(InvalidSourceSpecError) as exc_info:
        await create_info_source(session, url="https://example.com/p", source_specs=[bad_spec])
    assert exc_info.value.errors


@pytest.mark.asyncio
async def test_mixed_algorithm_families_rejected(session):
    """All specs must share a content-kind family (html_text or json)."""
    specs = [_spec("full_page"), _spec("jsonpath")]
    with pytest.raises(MixedAlgorithmFamilyError):
        await create_info_source(session, url="https://example.com/p", source_specs=specs)


# ---------------------------------------------------------------------------
# Domain auto-creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_sets_domain_name(session):
    """domain_name is populated from the URL hostname on create."""
    src = await create_info_source(
        session, url="https://regulations.cannabis.ca.gov/path", source_specs=[_spec()]
    )
    assert src.domain_name == "regulations.cannabis.ca.gov"


@pytest.mark.asyncio
async def test_create_same_domain_twice_no_conflict(session):
    """Two InfoSources at the same domain reuse the domain row without error."""
    a = await create_info_source(
        session, url="https://example.com/a", source_specs=[_spec("full_page")]
    )
    b = await create_info_source(session, url="https://example.com/b", source_specs=[_spec("css")])
    assert a.domain_name == b.domain_name == "example.com"


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


def test_error_hierarchy():
    assert issubclass(InvalidSourceSpecError, CreateInfoSourceError)
    assert issubclass(InvalidUrlError, CreateInfoSourceError)
    assert issubclass(MixedAlgorithmFamilyError, CreateInfoSourceError)
