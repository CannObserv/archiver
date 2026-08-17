"""Tests for assign_rep_spec — bind a RepSpec to an InfoItem with effective dating."""

from datetime import UTC, datetime

import pytest
from ulid import ULID

from src.core.models import InfoItem, RepSpec
from src.core.tools.assign_rep_spec import (
    AssignmentError,
    InfoItemNotFoundError,
    RepFieldsIncompleteError,
    RepFieldsUnrenderableError,
    RepSpecNotFoundError,
    assign_rep_spec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(rep_fields: dict | None = None) -> InfoItem:
    return InfoItem(name="test-item", rep_fields=rep_fields or {})


def _make_spec(
    required_fields: list[str] | None = None, path_template: str | None = None
) -> RepSpec:
    doc: dict = {"required_fields": required_fields or []}
    if path_template is not None:
        doc["path_template"] = path_template
    return RepSpec(provider="test", name="test-spec", schema_version=1, document=doc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_active_assignment(session):
    """Creates an active InfoItemRepSpec with public_url=None."""
    item = _make_item(rep_fields={"org": {"acronym": "wslcb"}})
    spec = _make_spec(required_fields=["org.acronym"])
    session.add(item)
    session.add(spec)
    await session.flush()

    assignment = await assign_rep_spec(
        session,
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
    )

    assert assignment.info_item_id == item.info_item_id
    assert assignment.rep_spec_id == spec.rep_spec_id
    assert assignment.deactivated_at is None
    assert assignment.public_url is None
    assert assignment.activated_at is not None


@pytest.mark.asyncio
async def test_info_item_not_found_raises(session):
    """Raises InfoItemNotFoundError for a non-existent info_item_id."""
    spec = _make_spec()
    session.add(spec)
    await session.flush()

    with pytest.raises(InfoItemNotFoundError):
        await assign_rep_spec(
            session,
            info_item_id=ULID(),
            rep_spec_id=spec.rep_spec_id,
        )


@pytest.mark.asyncio
async def test_rep_spec_not_found_raises(session):
    """Raises RepSpecNotFoundError for a non-existent rep_spec_id."""
    item = _make_item()
    session.add(item)
    await session.flush()

    with pytest.raises(RepSpecNotFoundError):
        await assign_rep_spec(
            session,
            info_item_id=item.info_item_id,
            rep_spec_id=ULID(),
        )


@pytest.mark.asyncio
async def test_missing_required_field_raises(session):
    """Raises RepFieldsIncompleteError when rep_fields is missing a required field."""
    item = _make_item(rep_fields={"org": {"title": "Washington LCB"}})
    spec = _make_spec(required_fields=["org.acronym"])
    session.add(item)
    session.add(spec)
    await session.flush()

    with pytest.raises(RepFieldsIncompleteError):
        await assign_rep_spec(
            session,
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
        )


@pytest.mark.asyncio
async def test_rep_fields_incomplete_error_carries_missing(session):
    """RepFieldsIncompleteError.missing contains the validation errors structure."""
    item = _make_item(rep_fields={})
    spec = _make_spec(required_fields=["org.acronym"])
    session.add(item)
    session.add(spec)
    await session.flush()

    with pytest.raises(RepFieldsIncompleteError) as exc_info:
        await assign_rep_spec(
            session,
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
        )

    err = exc_info.value
    assert isinstance(err.missing, list)
    assert len(err.missing) > 0
    # Each entry is a dict with 'path' and 'message' keys
    assert all("path" in e and "message" in e for e in err.missing)


@pytest.mark.asyncio
async def test_custom_activated_at_honored(session):
    """A caller-supplied activated_at is stored verbatim."""
    item = _make_item(rep_fields={"org": {"acronym": "wslcb"}})
    spec = _make_spec(required_fields=["org.acronym"])
    session.add(item)
    session.add(spec)
    await session.flush()

    custom_ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
    assignment = await assign_rep_spec(
        session,
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=custom_ts,
    )

    assert assignment.activated_at == custom_ts


@pytest.mark.asyncio
async def test_assignment_error_is_base_class(session):
    """Both typed errors inherit from AssignmentError."""
    assert issubclass(InfoItemNotFoundError, AssignmentError)
    assert issubclass(RepSpecNotFoundError, AssignmentError)
    assert issubclass(RepFieldsIncompleteError, AssignmentError)


@pytest.mark.asyncio
async def test_assignment_refused_when_a_bag_value_cannot_be_a_path_segment(session):
    """Present and non-null satisfies required_fields; it does not make a path (CR #5).

    Assignment is the last synchronous moment to fix it — the document freezes
    here (#83), and afterwards the failure is a bus fact on a service that
    cannot repair it.
    """
    item = _make_item(rep_fields={"org": {"name": "WA LCB"}})
    spec = _make_spec(
        required_fields=["org.name"],
        path_template="archive/{org.name}/{source_revision.id}.html",
    )
    session.add(item)
    session.add(spec)
    await session.flush()

    with pytest.raises(RepFieldsUnrenderableError):
        await assign_rep_spec(session, info_item_id=item.info_item_id, rep_spec_id=spec.rep_spec_id)


@pytest.mark.asyncio
async def test_assignment_allowed_when_the_bag_renders(session):
    item = _make_item(rep_fields={"org": {"name": "wa-lcb"}})
    spec = _make_spec(
        required_fields=["org.name"],
        path_template="archive/{org.name}/{source_revision.id}.html",
    )
    session.add(item)
    session.add(spec)
    await session.flush()

    assignment = await assign_rep_spec(
        session, info_item_id=item.info_item_id, rep_spec_id=spec.rep_spec_id
    )
    assert assignment.deactivated_at is None


@pytest.mark.asyncio
async def test_unrenderable_error_is_an_assignment_error(session):
    """Callers that catch the family keep catching it."""
    assert issubclass(RepFieldsUnrenderableError, AssignmentError)
