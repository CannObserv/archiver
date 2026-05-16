"""Tests for the bind_info_source core tool."""

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoSource
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    FragmentParentMismatchError,
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    RoleShapeMismatchError,
    bind_info_source,
)


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


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


@pytest.fixture
async def root_src(session):
    src = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def other_root(session):
    src = InfoSource(source_spec=_root_doc("https://example.com/q"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def frag_of_root(session, root_src):
    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_of_other(session, other_root):
    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=other_root.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


# --- happy paths ---


@pytest.mark.asyncio
async def test_bind_root_with_null_role(session, item, root_src):
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    assert binding.role is None
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_bind_fragment_with_cross_check(session, item, root_src, frag_of_root):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_of_root.info_source_id,
        role="cross_check",
    )
    assert binding.role == "cross_check"


# --- shape consistency ---


@pytest.mark.asyncio
async def test_root_with_role_rejected(session, item, root_src):
    with pytest.raises(RoleShapeMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=root_src.info_source_id,
            role="sub_aspect",
        )


@pytest.mark.asyncio
async def test_fragment_with_null_role_rejected(session, item, root_src, frag_of_root):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(RoleShapeMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_root.info_source_id,
            role=None,
        )


# --- fragment-shares-root ---


@pytest.mark.asyncio
async def test_fragment_under_different_root_rejected(session, item, root_src, frag_of_other):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(FragmentParentMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_other.info_source_id,
            role="sub_aspect",
        )


@pytest.mark.asyncio
async def test_fragment_without_active_root_rejected(session, item, frag_of_root):
    with pytest.raises(ActiveRootMissingError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_root.info_source_id,
            role="cross_check",
        )


# --- existence ---


@pytest.mark.asyncio
async def test_unknown_info_item(session, root_src):
    with pytest.raises(InfoItemNotFoundError):
        await bind_info_source(
            session,
            info_item_id=ULID(),
            info_source_id=root_src.info_source_id,
            role=None,
        )


@pytest.mark.asyncio
async def test_unknown_info_source(session, item):
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=ULID(),
            role=None,
        )
