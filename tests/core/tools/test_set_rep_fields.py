"""Tests for set_rep_fields — the validated rep_fields write (archiver#302)."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.tools.assign_rep_spec import (
    InfoItemNotFoundError,
    RepFieldsIncompleteError,
    assign_rep_spec,
)
from src.core.tools.set_rep_fields import (
    CODE_INCOMPLETE,
    CODE_UNRENDERABLE,
    RepFieldsInvalidError,
    RepFieldsMoveError,
    RepFieldsRefusedError,
    RepFieldsWriteError,
    set_rep_fields,
)

_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"


def _spec(name: str, *required: str, path_template: str = _ORG_PATH) -> RepSpec:
    return RepSpec(
        provider="gcs",
        name=name,
        schema_version=1,
        document={"required_fields": list(required), "path_template": path_template},
    )


async def _assigned(session, bag: dict, *specs: RepSpec) -> InfoItem:
    item = InfoItem(name="bagged", rep_fields=bag)
    session.add(item)
    session.add_all(specs)
    await session.flush()
    for spec in specs:
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
    await session.flush()
    return item


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unassigned_item_takes_any_well_shaped_bag(session):
    item = await _assigned(session, {})

    saved = await set_rep_fields(
        session, info_item_id=item.info_item_id, rep_fields={"org": {"title": "WA LCB"}}
    )

    assert saved.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_a_bag_that_keeps_every_assignment_whole_is_written(session):
    item = await _assigned(
        session,
        {"org": {"title": "WA LCB"}},
        _spec("org spec", "org.title_slug"),
    )

    bag = {"org": {"title": "WA LCB", "acronym": "WSLCB"}}
    saved = await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields=bag)

    assert saved.rep_fields == bag


@pytest.mark.asyncio
async def test_resaving_the_same_bag_is_not_a_move(session):
    bag = {"org": {"title": "WA LCB"}}
    item = await _assigned(session, bag, _spec("org spec", "org.title_slug"))

    saved = await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields=dict(bag))

    assert saved.rep_fields == bag


@pytest.mark.asyncio
async def test_a_deactivated_assignment_does_not_constrain_the_bag(session):
    item = await _assigned(session, {"org": {"title": "WA LCB"}}, _spec("old", "org.title_slug"))
    row = await session.scalar(
        select(InfoItemRepSpec).where(InfoItemRepSpec.info_item_id == item.info_item_id)
    )
    row.deactivated_at = datetime.now(UTC)
    await session.flush()

    saved = await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields={})

    assert saved.rep_fields == {}


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_item_raises_not_found(session):
    with pytest.raises(InfoItemNotFoundError):
        await set_rep_fields(session, info_item_id=ULID(), rep_fields={})


@pytest.mark.asyncio
async def test_a_bag_off_the_v1_shape_is_refused_before_any_assignment_check(session):
    item = await _assigned(session, {"org": {"title": "WA LCB"}}, _spec("s", "org.title_slug"))

    with pytest.raises(RepFieldsInvalidError) as exc_info:
        await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields={"flat": "x"})

    assert [e["path"] for e in exc_info.value.errors] == ["/flat"]
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_dropping_a_required_key_is_refused_naming_the_assignment_and_key(session):
    spec = _spec("Org spec", "org.title_slug")
    item = await _assigned(session, {"org": {"title": "WA LCB"}}, spec)

    with pytest.raises(RepFieldsRefusedError) as exc_info:
        await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields={})

    [refusal] = exc_info.value.refusals
    assert refusal.rep_spec_id == spec.rep_spec_id
    assert refusal.rep_spec_name == "Org spec"
    assert refusal.assignment_id is not None
    assert refusal.code == CODE_INCOMPLETE
    assert [e["path"] for e in refusal.errors] == ["/org/title_slug"]
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_every_broken_assignment_is_named_not_just_the_first(session):
    first = _spec("First", "org.title_slug")
    second = _spec(
        "Second",
        "info_item.name_slug",
        path_template="i/{info_item.name_slug}/{source_revision.id}",
    )
    item = await _assigned(
        session, {"org": {"title": "WA LCB"}, "info_item": {"name": "Notices"}}, first, second
    )

    with pytest.raises(RepFieldsRefusedError) as exc_info:
        await set_rep_fields(session, info_item_id=item.info_item_id, rep_fields={})

    assert {r.rep_spec_name for r in exc_info.value.refusals} == {"First", "Second"}


@pytest.mark.asyncio
async def test_a_value_that_cannot_render_is_refused_as_unrenderable(session):
    spec = _spec("Raw", "org.name", path_template="a/{org.name}/{source_revision.id}")
    item = await _assigned(session, {"org": {"name": "wa_lcb"}}, spec)

    with pytest.raises(RepFieldsRefusedError) as exc_info:
        await set_rep_fields(
            session, info_item_id=item.info_item_id, rep_fields={"org": {"name": "WA LCB"}}
        )

    [refusal] = exc_info.value.refusals
    assert refusal.code == CODE_UNRENDERABLE
    assert "org.name" in refusal.errors[0]["message"]


@pytest.mark.asyncio
async def test_a_valid_edit_that_moves_the_destination_is_refused_with_both_paths(session):
    spec = _spec("Org spec", "org.title_slug")
    item = await _assigned(session, {"org": {"title": "Old Name"}}, spec)

    with pytest.raises(RepFieldsMoveError) as exc_info:
        await set_rep_fields(
            session, info_item_id=item.info_item_id, rep_fields={"org": {"title": "New Name"}}
        )

    [move] = exc_info.value.moves
    assert move.rep_spec_name == "Org spec"
    assert move.before.startswith("organizations/old_name/")
    assert move.after.startswith("organizations/new_name/")
    await session.refresh(item)
    assert item.rep_fields == {"org": {"title": "Old Name"}}


@pytest.mark.asyncio
async def test_a_move_is_written_when_explicitly_allowed(session):
    item = await _assigned(session, {"org": {"title": "Old Name"}}, _spec("s", "org.title_slug"))

    saved = await set_rep_fields(
        session,
        info_item_id=item.info_item_id,
        rep_fields={"org": {"title": "New Name"}},
        allow_destination_change=True,
    )

    assert saved.rep_fields == {"org": {"title": "New Name"}}


@pytest.mark.asyncio
async def test_repairing_a_bag_that_could_not_render_is_not_a_move(session):
    """No path rendered from the old bag, so there is nothing for the new one to move."""
    item = await _assigned(session, {}, _spec("s", "org.title_slug"))

    saved = await set_rep_fields(
        session, info_item_id=item.info_item_id, rep_fields={"org": {"title": "WA LCB"}}
    )

    assert saved.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_repairing_a_malformed_stored_bag_is_not_a_move(session):
    """The pre-#302 save stored any JSON object, so an assigned item can hold a
    bag the v1 shape refuses. Probing it for the "before" path must fail as a
    render error (no path, so no move), not crash the repair (CR 4)."""
    item = await _assigned(session, {"org": "flat"}, _spec("s", "org.title_slug"))

    saved = await set_rep_fields(
        session, info_item_id=item.info_item_id, rep_fields={"org": {"title": "WA LCB"}}
    )

    assert saved.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_every_refusal_is_a_write_error():
    for cls in (RepFieldsInvalidError, RepFieldsRefusedError, RepFieldsMoveError):
        assert issubclass(cls, RepFieldsWriteError)


# ---------------------------------------------------------------------------
# Concurrency — the InfoItem row serializes a save against an assign
# ---------------------------------------------------------------------------


async def _committed_item_and_spec(make_session, committed_rows, bag: dict):
    async with make_session() as setup:
        spec = _spec("race spec", "org.title_slug")
        item = InfoItem(name="race item", rep_fields=bag)
        setup.add_all([spec, item])
        await setup.commit()
        committed_rows += [(RepSpec, spec.rep_spec_id), (InfoItem, item.info_item_id)]
        return item.info_item_id, spec.rep_spec_id


@pytest.mark.asyncio
async def test_an_assign_waits_for_a_save_and_then_sees_the_new_bag(test_engine, committed_rows):
    """Without the item lock both pass on their own snapshot and both commit,
    leaving the spec assigned to a bag that cannot serve it (archiver#302)."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    item_id, spec_id = await _committed_item_and_spec(
        make_session, committed_rows, {"org": {"title": "WA LCB"}}
    )

    async with make_session() as saver, make_session() as assigner:
        await set_rep_fields(saver, info_item_id=item_id, rep_fields={})

        task = asyncio.create_task(
            assign_rep_spec(assigner, info_item_id=item_id, rep_spec_id=spec_id)
        )
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "assignment proceeded while a save held the InfoItem row"

        await saver.commit()
        with pytest.raises(RepFieldsIncompleteError):
            await asyncio.wait_for(task, timeout=10.0)
        await assigner.rollback()


@pytest.mark.asyncio
async def test_a_save_waits_for_an_assign_and_then_honours_it(test_engine, committed_rows):
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    item_id, spec_id = await _committed_item_and_spec(
        make_session, committed_rows, {"org": {"title": "WA LCB"}}
    )

    async with make_session() as assigner, make_session() as saver:
        assignment = await assign_rep_spec(assigner, info_item_id=item_id, rep_spec_id=spec_id)

        task = asyncio.create_task(set_rep_fields(saver, info_item_id=item_id, rep_fields={}))
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "save proceeded while an assign held the InfoItem row"

        await assigner.commit()
        committed_rows.append((InfoItemRepSpec, assignment.id))
        with pytest.raises(RepFieldsRefusedError):
            await asyncio.wait_for(task, timeout=10.0)
        await saver.rollback()
