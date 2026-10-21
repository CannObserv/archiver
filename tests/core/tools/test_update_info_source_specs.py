"""Tests for update_info_source_specs."""

import pytest
from ulid import ULID

from src.core.models import InfoSource
from src.core.tools.update_info_source_specs import (
    InfoSourceNotFoundError,
    InvalidSourceSpecError,
    MixedAlgorithmFamilyError,
    update_info_source_specs,
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


@pytest.fixture
async def source(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    return src


@pytest.mark.asyncio
async def test_update_replaces_specs(session, source):
    new_specs = [_spec("full_page"), _spec("css")]
    updated = await update_info_source_specs(
        session, info_source_id=source.info_source_id, source_specs=new_specs
    )
    assert updated.source_specs == new_specs
    assert updated.url == source.url  # URL unchanged


@pytest.mark.asyncio
async def test_unknown_id_raises(session):
    with pytest.raises(InfoSourceNotFoundError):
        await update_info_source_specs(session, info_source_id=ULID(), source_specs=[_spec()])


@pytest.mark.asyncio
async def test_empty_list_rejected(session, source):
    with pytest.raises(InvalidSourceSpecError):
        await update_info_source_specs(
            session, info_source_id=source.info_source_id, source_specs=[]
        )


@pytest.mark.asyncio
async def test_invalid_spec_rejected(session, source):
    bad = {"schema_version": 1, "extraction": {"algorithm": "css"}, "fingerprint": {}}
    with pytest.raises(InvalidSourceSpecError):
        await update_info_source_specs(
            session, info_source_id=source.info_source_id, source_specs=[bad]
        )


@pytest.mark.asyncio
async def test_mixed_families_rejected(session, source):
    """The message names the families sorted, not in a set's hash-seeded order (#356 CR 1)."""
    with pytest.raises(MixedAlgorithmFamilyError, match=r"\['html_text', 'json'\]"):
        await update_info_source_specs(
            session,
            info_source_id=source.info_source_id,
            source_specs=[_spec("jsonpath", "$.items[*]"), _spec("xpath", "//x")],
        )


@pytest.mark.asyncio
async def test_full_page_pairs_with_jsonpath(session, source):
    """``full_page`` is family-neutral (#356 D1)."""
    updated = await update_info_source_specs(
        session,
        info_source_id=source.info_source_id,
        source_specs=[_spec("jsonpath", "$.items[*]"), _spec("full_page")],
    )
    assert [s["extraction"]["algorithm"] for s in updated.source_specs] == [
        "jsonpath",
        "full_page",
    ]
