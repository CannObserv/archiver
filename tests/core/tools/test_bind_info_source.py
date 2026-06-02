"""Tests for the bind_info_source core tool."""

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoSource
from src.core.tools.bind_info_source import (
    ActiveRootAlreadyExistsError,
    ActiveRootMissingError,
    AlgorithmFamilyMismatchError,
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


def _root_json_doc(url: str) -> dict:
    """Root doc using jsonpath — establishes a JSON-family primary."""
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "jsonpath", "selector": "$"},
        "fingerprint": {},
    }


def _fragment_jsonpath_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "jsonpath", "selector": "$.items[*]"},
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


@pytest.fixture
async def root_src_json(session):
    """Root InfoSource whose primary algorithm is jsonpath (JSON family)."""
    src = InfoSource(source_spec=_root_json_doc("https://example.com/api"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def frag_css_of_root(session, root_src):
    """Fragment under HTML-family root, using css — same family, should bind."""
    frag = InfoSource(
        source_spec=_fragment_doc(),  # algorithm=css
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_jsonpath_of_html_root(session, root_src):
    """Fragment under HTML-family root, using jsonpath — CROSS-FAMILY, must reject."""
    frag = InfoSource(
        source_spec=_fragment_jsonpath_doc(),
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_css_of_json_root(session, root_src_json):
    """Fragment under JSON-family root, using css — CROSS-FAMILY, must reject."""
    frag = InfoSource(
        source_spec=_fragment_doc(),  # algorithm=css
        schema_version=1,
        parent_info_source_id=root_src_json.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_jsonpath_of_json_root(session, root_src_json):
    """Fragment under JSON-family root, using jsonpath — same family, should bind."""
    frag = InfoSource(
        source_spec=_fragment_jsonpath_doc(),
        schema_version=1,
        parent_info_source_id=root_src_json.info_source_id,
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


# --- active-root collision guard ---


@pytest.mark.asyncio
async def test_second_active_root_rejected(session, item, root_src, other_root):
    """A second NULL-role bind on the same InfoItem raises ActiveRootAlreadyExistsError."""
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(ActiveRootAlreadyExistsError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=other_root.info_source_id,
            role=None,
        )
    assert exc_info.value.existing_info_source_id == root_src.info_source_id


# --- shape consistency ---


@pytest.mark.asyncio
async def test_root_with_role_rejected(session, item, root_src):
    with pytest.raises(RoleShapeMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=root_src.info_source_id,
            role="cross_check",
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
            role="cross_check",
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


# --- algorithm-family compatibility (issue #22) ---


@pytest.mark.asyncio
async def test_same_family_fragment_html_html_accepted(session, item, root_src, frag_css_of_root):
    """css fragment under full_page primary — both html_text, should bind."""
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_css_of_root.info_source_id,
        role="cross_check",
    )
    assert binding.role == "cross_check"


@pytest.mark.asyncio
async def test_same_family_fragment_json_json_accepted(
    session, item, root_src_json, frag_jsonpath_of_json_root
):
    """jsonpath fragment under jsonpath primary — both json, should bind."""
    await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=root_src_json.info_source_id,
        role=None,
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_jsonpath_of_json_root.info_source_id,
        role="cross_check",
    )
    assert binding.role == "cross_check"


@pytest.mark.asyncio
async def test_cross_family_jsonpath_under_html_rejected(
    session, item, root_src, frag_jsonpath_of_html_root
):
    """jsonpath fragment under full_page (html_text) primary — must reject."""
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(AlgorithmFamilyMismatchError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_jsonpath_of_html_root.info_source_id,
            role="cross_check",
        )
    assert exc_info.value.expected_family == "html_text"
    assert exc_info.value.actual_algorithm == "jsonpath"


@pytest.mark.asyncio
async def test_cross_family_css_under_jsonpath_rejected(
    session, item, root_src_json, frag_css_of_json_root
):
    """css fragment under jsonpath primary — must reject (the other direction)."""
    await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=root_src_json.info_source_id,
        role=None,
    )
    with pytest.raises(AlgorithmFamilyMismatchError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_css_of_json_root.info_source_id,
            role="cross_check",
        )
    assert exc_info.value.expected_family == "json"
    assert exc_info.value.actual_algorithm == "css"
