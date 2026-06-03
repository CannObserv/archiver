"""Tests for bind_revision — pin an InfoItem to a SourceRevision (idempotent)."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoSource, SourceRevision
from src.core.tools.bind_revision import (
    BindError,
    InfoItemNotFoundError,
    SourceRevisionNotFoundError,
    bind_revision,
)


def _spec_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item() -> InfoItem:
    return InfoItem(name="test-item")


def _make_source() -> InfoSource:
    return InfoSource(url=f"https://example.com/{ULID()}", source_specs=[_spec_doc()])


def _make_revision(info_source_id: ULID) -> SourceRevision:
    return SourceRevision(
        info_source_id=info_source_id,
        content_fingerprint=str(ULID()),
        captured_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_new_binding(session):
    """Creates a new InfoItemSourceRevision with bound_at set."""
    item = _make_item()
    source = _make_source()
    session.add(item)
    session.add(source)
    await session.flush()

    rev = _make_revision(source.info_source_id)
    session.add(rev)
    await session.flush()

    binding = await bind_revision(
        session,
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
    )

    assert binding.info_item_id == item.info_item_id
    assert binding.source_revision_id == rev.source_revision_id
    assert binding.bound_at is not None


@pytest.mark.asyncio
async def test_idempotent_second_call_returns_same_row(session):
    """Calling bind_revision twice with same args returns the same row without error."""
    item = _make_item()
    source = _make_source()
    session.add(item)
    session.add(source)
    await session.flush()

    rev = _make_revision(source.info_source_id)
    session.add(rev)
    await session.flush()

    first = await bind_revision(
        session,
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
    )
    second = await bind_revision(
        session,
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
    )

    assert first.info_item_id == second.info_item_id
    assert first.source_revision_id == second.source_revision_id
    assert first.bound_at == second.bound_at


@pytest.mark.asyncio
async def test_info_item_not_found_raises(session):
    """Raises InfoItemNotFoundError for a non-existent info_item_id."""
    source = _make_source()
    session.add(source)
    await session.flush()

    rev = _make_revision(source.info_source_id)
    session.add(rev)
    await session.flush()

    with pytest.raises(InfoItemNotFoundError):
        await bind_revision(
            session,
            info_item_id=ULID(),
            source_revision_id=rev.source_revision_id,
        )


@pytest.mark.asyncio
async def test_source_revision_not_found_raises(session):
    """Raises SourceRevisionNotFoundError for a non-existent source_revision_id."""
    item = _make_item()
    session.add(item)
    await session.flush()

    with pytest.raises(SourceRevisionNotFoundError):
        await bind_revision(
            session,
            info_item_id=item.info_item_id,
            source_revision_id=ULID(),
        )


@pytest.mark.asyncio
async def test_custom_bound_at_honored(session):
    """A caller-supplied bound_at is stored verbatim."""
    item = _make_item()
    source = _make_source()
    session.add(item)
    session.add(source)
    await session.flush()

    rev = _make_revision(source.info_source_id)
    session.add(rev)
    await session.flush()

    custom_ts = datetime(2025, 3, 10, 9, 0, 0, tzinfo=UTC)
    binding = await bind_revision(
        session,
        info_item_id=item.info_item_id,
        source_revision_id=rev.source_revision_id,
        bound_at=custom_ts,
    )

    assert binding.bound_at == custom_ts


@pytest.mark.asyncio
async def test_bind_error_is_base_class():
    """Both typed errors inherit from BindError."""
    assert issubclass(InfoItemNotFoundError, BindError)
    assert issubclass(SourceRevisionNotFoundError, BindError)
