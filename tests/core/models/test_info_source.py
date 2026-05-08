"""InfoSource model tests."""

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoSource


def _root_doc(url: str) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }


@pytest.mark.asyncio
async def test_root_source_creates_with_url(session):
    src = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add(src)
    await session.commit()
    await session.refresh(src)
    assert str(src.info_source_id)  # ULID generated
    assert src.url == "https://example.com/p"
    assert src.parent_info_source_id is None


@pytest.mark.asyncio
async def test_fragment_source_requires_parent(session):
    parent = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add(parent)
    await session.commit()

    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=parent.info_source_id,
    )
    session.add(frag)
    await session.commit()
    await session.refresh(frag)
    assert frag.url is None
    assert frag.parent_info_source_id == parent.info_source_id


@pytest.mark.asyncio
async def test_xor_constraint_root_with_parent_rejected(session):
    parent = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add(parent)
    await session.commit()

    bad = InfoSource(
        source_spec=_root_doc("https://example.com/q"),
        schema_version=1,
        parent_info_source_id=parent.info_source_id,
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_xor_constraint_fragment_without_parent_rejected(session):
    bad = InfoSource(source_spec=_fragment_doc(), schema_version=1)
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_url_unique(session):
    a = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    b = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add_all([a, b])
    with pytest.raises(IntegrityError):
        await session.commit()
