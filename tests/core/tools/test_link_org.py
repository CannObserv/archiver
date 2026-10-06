"""link_org — link or unlink an InfoItem's Power Map org (archiver#304).

Fetch, upsert the snapshot, set the FK, under the InfoItem row lock. Linking
drops the stored ``org.title``/``org.acronym`` (the org supplies them now);
unlinking writes the org's values back so nothing moves. A link that moves an
active assignment's path is #302's move contract, not a new one.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, PmOrganization, RepSpec
from src.core.power_map import PowerMapUnavailableError
from src.core.power_map.snapshots import OrgUnnamedError
from src.core.tools.assign_rep_spec import InfoItemNotFoundError
from src.core.tools.link_org import (
    OrgNotFoundError,
    PowerMapNotConfiguredError,
    link_org,
)
from src.core.tools.set_rep_fields import (
    RepFieldsInvalidError,
    RepFieldsMoveError,
    RepFieldsRefusedError,
    set_rep_fields,
)
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, FakePowerMap, org

OTHER_ID = "01JPM00000000000000000000C"
_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"
_WSLCB_SLUG = "washington_state_liquor_and_cannabis_board"


def _spec(name: str, *required: str, path_template: str = _ORG_PATH) -> RepSpec:
    return RepSpec(
        provider="gcs",
        name=name,
        schema_version=1,
        document={"required_fields": list(required), "path_template": path_template},
    )


async def _item(session, bag: dict, *specs: RepSpec) -> InfoItem:
    item = InfoItem(name="linkable", rep_fields=bag)
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
# Linking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_snapshots_the_org_and_sets_the_fk(session):
    item = await _item(session, {"info_item": {"name": "N"}})
    pm = FakePowerMap(org())

    linked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm
    )

    assert linked.pm_org_id == WSLCB_ID
    assert linked.rep_fields == {"info_item": {"name": "N"}}
    row = await session.get(PmOrganization, WSLCB_ID)
    assert row is not None and row.name == WSLCB_NAME
    assert pm.calls == [("get_org", WSLCB_ID, None)]


@pytest.mark.asyncio
async def test_an_unknown_item_is_not_found_before_power_map_is_asked(session):
    pm = FakePowerMap(org())
    with pytest.raises(InfoItemNotFoundError):
        await link_org(session, info_item_id=ULID(), pm_org_id=WSLCB_ID, power_map=pm)
    assert pm.calls == []


@pytest.mark.asyncio
async def test_linking_with_power_map_unconfigured_is_refused(session):
    item = await _item(session, {})
    with pytest.raises(PowerMapNotConfiguredError):
        await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=None)


@pytest.mark.asyncio
async def test_power_map_unavailable_links_nothing(session):
    item = await _item(session, {})
    pm = FakePowerMap(org())
    pm.unavailable = PowerMapUnavailableError("request timed out")

    with pytest.raises(PowerMapUnavailableError):
        await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)

    await session.refresh(item)
    assert item.pm_org_id is None
    assert await session.get(PmOrganization, WSLCB_ID) is None


@pytest.mark.asyncio
async def test_an_org_power_map_does_not_have_is_not_found(session):
    item = await _item(session, {})
    with pytest.raises(OrgNotFoundError):
        await link_org(
            session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=FakePowerMap()
        )


@pytest.mark.asyncio
async def test_a_merged_id_links_the_winner(session):
    item = await _item(session, {})
    pm = FakePowerMap(org(pm_org_id=OTHER_ID, name="Winner Board", acronym="WB"))
    pm.merged[WSLCB_ID] = OTHER_ID

    linked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm
    )

    assert linked.pm_org_id == OTHER_ID
    assert pm.calls == [("get_org", WSLCB_ID, None), ("get_org", OTHER_ID, None)]


@pytest.mark.asyncio
async def test_a_merge_whose_winner_is_gone_is_not_found(session):
    item = await _item(session, {})
    pm = FakePowerMap()
    pm.merged[WSLCB_ID] = OTHER_ID
    with pytest.raises(OrgNotFoundError):
        await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)


@pytest.mark.asyncio
async def test_an_org_with_no_name_cannot_be_linked(session):
    item = await _item(session, {})
    with pytest.raises(OrgUnnamedError):
        await link_org(
            session,
            info_item_id=item.info_item_id,
            pm_org_id=WSLCB_ID,
            power_map=FakePowerMap(org(name=None)),
        )


@pytest.mark.asyncio
async def test_hand_typed_keys_equal_to_power_maps_are_dropped_silently(session):
    item = await _item(
        session,
        {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}, "info_item": {"name": "N"}},
        _spec("org spec", "org.title_slug"),
    )

    linked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=FakePowerMap(org())
    )

    assert linked.pm_org_id == WSLCB_ID
    assert linked.rep_fields == {"info_item": {"name": "N"}}


@pytest.mark.asyncio
async def test_a_stored_slug_override_survives_the_link(session):
    item = await _item(session, {"org": {"title": WSLCB_NAME, "title_slug": "wslcb"}})

    linked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=FakePowerMap(org())
    )

    assert linked.rep_fields == {"org": {"title_slug": "wslcb"}}


@pytest.mark.asyncio
async def test_different_hand_typed_keys_that_move_a_path_are_refused_with_both_paths(session):
    item = await _item(
        session,
        {"org": {"title": "WA LCB"}},
        _spec("org spec", "org.title_slug"),
    )

    with pytest.raises(RepFieldsMoveError) as exc:
        await link_org(
            session,
            info_item_id=item.info_item_id,
            pm_org_id=WSLCB_ID,
            power_map=FakePowerMap(org()),
        )

    (move,) = exc.value.moves
    assert move.rep_spec_name == "org spec"
    assert move.before.startswith("organizations/wa_lcb/")
    assert move.after.startswith(f"organizations/{_WSLCB_SLUG}/")
    await session.refresh(item)
    assert item.pm_org_id is None
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_a_moving_link_is_written_when_allowed(session):
    item = await _item(session, {"org": {"title": "WA LCB"}}, _spec("org spec", "org.title_slug"))

    linked = await link_org(
        session,
        info_item_id=item.info_item_id,
        pm_org_id=WSLCB_ID,
        power_map=FakePowerMap(org()),
        allow_destination_change=True,
    )

    assert linked.pm_org_id == WSLCB_ID
    assert linked.rep_fields == {}


@pytest.mark.asyncio
async def test_different_hand_typed_keys_no_assignment_renders_are_just_dropped(session):
    item = await _item(session, {"org": {"title": "WA LCB"}})

    linked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=FakePowerMap(org())
    )

    assert linked.rep_fields == {}


@pytest.mark.asyncio
async def test_a_link_that_breaks_an_assignment_is_refused(session):
    """The org has no acronym, and the hand-typed one the spec needs is dropped."""
    item = await _item(
        session,
        {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}},
        _spec("acronym spec", "org.acronym", path_template="{org.acronym}/{source_revision.id}"),
    )

    with pytest.raises(RepFieldsRefusedError) as exc:
        await link_org(
            session,
            info_item_id=item.info_item_id,
            pm_org_id=WSLCB_ID,
            power_map=FakePowerMap(org(acronym=None)),
        )

    assert [r.rep_spec_name for r in exc.value.refusals] == ["acronym spec"]


@pytest.mark.asyncio
async def test_relinking_to_another_org_that_moves_a_path_is_refused(session):
    item = await _item(session, {"org": {"title": WSLCB_NAME}}, _spec("org spec", "org.title_slug"))
    pm = FakePowerMap(org(), org(pm_org_id=OTHER_ID, name="Other Board", acronym="OB"))
    await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)

    with pytest.raises(RepFieldsMoveError):
        await link_org(session, info_item_id=item.info_item_id, pm_org_id=OTHER_ID, power_map=pm)


@pytest.mark.asyncio
async def test_linking_refreshes_an_existing_snapshot(session):
    item = await _item(session, {})
    pm = FakePowerMap(org())
    await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)
    pm.rename(WSLCB_ID, "WA Cannabis Board", etag='"v2"')

    await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)

    row = await session.get(PmOrganization, WSLCB_ID)
    assert row.name == "WA Cannabis Board"
    assert row.renamed_from == WSLCB_NAME


# ---------------------------------------------------------------------------
# Unlinking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlinking_writes_the_orgs_values_back_so_nothing_moves(session):
    item = await _item(
        session,
        {"org": {"title": WSLCB_NAME}, "info_item": {"name": "N"}},
        _spec("org spec", "org.title_slug"),
    )
    pm = FakePowerMap(org())
    await link_org(session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=pm)

    unlinked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=None, power_map=None
    )

    assert unlinked.pm_org_id is None
    assert unlinked.rep_fields == {
        "org": {"title": WSLCB_NAME, "acronym": "WSLCB"},
        "info_item": {"name": "N"},
    }
    # The snapshot stays: provenance, and other items may link it.
    assert await session.get(PmOrganization, WSLCB_ID) is not None


@pytest.mark.asyncio
async def test_unlinking_an_unlinked_item_changes_nothing(session):
    item = await _item(session, {"org": {"title": "WA LCB"}})

    unlinked = await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=None, power_map=None
    )

    assert unlinked.pm_org_id is None
    assert unlinked.rep_fields == {"org": {"title": "WA LCB"}}


# ---------------------------------------------------------------------------
# While linked: set_rep_fields reads the org and refuses its keys
# ---------------------------------------------------------------------------


async def _linked(session, bag: dict, *specs: RepSpec) -> InfoItem:
    item = await _item(session, bag, *specs)
    await link_org(
        session, info_item_id=item.info_item_id, pm_org_id=WSLCB_ID, power_map=FakePowerMap(org())
    )
    return item


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["title", "acronym"])
async def test_a_linked_item_refuses_a_stored_org_owned_key(session, key):
    item = await _linked(session, {})

    with pytest.raises(RepFieldsInvalidError) as exc:
        await set_rep_fields(
            session, info_item_id=item.info_item_id, rep_fields={"org": {key: "Hand Typed"}}
        )

    assert [e["path"] for e in exc.value.errors] == [f"/org/{key}"]


@pytest.mark.asyncio
async def test_a_linked_item_keeps_other_org_keys_as_overrides(session):
    item = await _linked(session, {})

    saved = await set_rep_fields(
        session, info_item_id=item.info_item_id, rep_fields={"org": {"title_slug": "wslcb"}}
    )

    assert saved.rep_fields == {"org": {"title_slug": "wslcb"}}


@pytest.mark.asyncio
async def test_a_linked_items_assignment_is_satisfied_by_the_org(session):
    """No stored org.title, yet org.title_slug is there: the gate reads the org."""
    item = await _linked(
        session, {"org": {"title": WSLCB_NAME}}, _spec("org spec", "org.title_slug")
    )

    saved = await set_rep_fields(
        session, info_item_id=item.info_item_id, rep_fields={"info_item": {"name": "N"}}
    )

    assert saved.rep_fields == {"info_item": {"name": "N"}}


@pytest.mark.asyncio
async def test_a_linked_items_move_check_reads_the_org(session):
    item = await _linked(
        session, {"org": {"title": WSLCB_NAME}}, _spec("org spec", "org.title_slug")
    )

    with pytest.raises(RepFieldsMoveError) as exc:
        await set_rep_fields(
            session, info_item_id=item.info_item_id, rep_fields={"org": {"title_slug": "wslcb"}}
        )

    (move,) = exc.value.moves
    assert move.before.startswith(f"organizations/{_WSLCB_SLUG}/")
    assert move.after.startswith("organizations/wslcb/")


# ---------------------------------------------------------------------------
# The InfoItem row lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_save_waits_for_a_link_and_then_reads_the_org(test_engine, committed_rows):
    """Without the item lock a save judges the bag against the pre-link org."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with make_session() as setup:
        item = InfoItem(name="race item", rep_fields={})
        setup.add(item)
        await setup.commit()
        committed_rows.append((InfoItem, item.info_item_id))
    committed_rows.insert(0, (PmOrganization, WSLCB_ID))  # deleted after the item

    async with make_session() as linker, make_session() as saver:
        await link_org(
            linker,
            info_item_id=item.info_item_id,
            pm_org_id=WSLCB_ID,
            power_map=FakePowerMap(org()),
        )

        task = asyncio.create_task(
            set_rep_fields(
                saver, info_item_id=item.info_item_id, rep_fields={"org": {"title": "X"}}
            )
        )
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "save proceeded while a link held the InfoItem row"

        await linker.commit()
        with pytest.raises(RepFieldsInvalidError):
            await asyncio.wait_for(task, timeout=10.0)
        await saver.rollback()
