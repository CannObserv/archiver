"""Tests for the rep_fields gate — whether one bag can serve one RepSpec (archiver#302)."""

import pytest
from ulid import ULID

from src.core.models import InfoItem
from src.core.rep_fields import OrgValues
from src.core.tools.rep_fields_gate import check_bag_against_spec, lock_info_item

_DOC = {
    "required_fields": ["org.title_slug"],
    "path_template": "organizations/{org.title_slug}/{source_revision.id}.html",
}


def test_a_bag_that_satisfies_and_renders_passes():
    check = check_bag_against_spec({"org": {"title": "WA LCB"}}, _DOC, org=None)
    assert check.ok
    assert check.missing == []
    assert check.unrenderable is None


def test_a_missing_required_key_is_reported_and_not_probed():
    """Probing a bag that lacks the key only restates the miss as a render error."""
    check = check_bag_against_spec({}, _DOC, org=None)
    assert not check.ok
    assert [m["path"] for m in check.missing] == ["/org/title_slug"]
    assert check.unrenderable is None


def test_a_present_value_that_cannot_render_is_reported():
    doc = {"required_fields": ["org.name"], "path_template": "a/{org.name}/{source_revision.id}"}
    check = check_bag_against_spec({"org": {"name": "WA LCB"}}, doc, org=None)
    assert not check.ok
    assert check.missing == []
    assert "org.name" in check.unrenderable


def test_a_document_without_required_fields_still_probes():
    doc = {"path_template": "a/{org.name}/{source_revision.id}"}
    check = check_bag_against_spec({}, doc, org=None)
    assert not check.ok
    assert check.unrenderable is not None


def test_a_linked_org_satisfies_the_spec():
    """archiver#303: the gate checks the effective bag, so the org's name counts."""
    check = check_bag_against_spec({}, _DOC, org=OrgValues(name="WA LCB", acronym=None))
    assert check.ok


@pytest.mark.asyncio
async def test_lock_info_item_returns_the_row(session):
    item = InfoItem(name="lock-me", rep_fields={})
    session.add(item)
    await session.flush()

    assert await lock_info_item(session, item.info_item_id) is item


@pytest.mark.asyncio
async def test_lock_info_item_returns_none_for_an_unknown_id(session):
    assert await lock_info_item(session, ULID()) is None
