"""InfoItem tags (archiver#362): the one tag rule, and the writes that use it.

D2: one rule in one function, used by the API, the dashboard and the importer.
Strip; refuse an empty tag, one over 255 characters (Watcher's limit), a comma
(the editor splits on it) or a control character; keep case; de-duplicate
exactly; at most 32 per item. Stored sorted (D1).

D4: the dashboard's add and remove are read-modify-write, so they lock the item
row ``FOR NO KEY UPDATE`` - two quick adds cannot lose one. ``set_tags`` replaces
the whole set: last writer wins, by design.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import InfoItem
from src.core.services.info_item_tags import (
    MAX_TAG_LENGTH,
    MAX_TAGS,
    InfoItemNotFoundError,
    TagError,
    add_tags,
    normalize_tags,
    remove_tag,
    set_tags,
    split_tags,
)

# --- D2: the rule, edge by edge ---


def test_tags_are_stripped_deduplicated_exactly_and_sorted():
    assert normalize_tags(["  zeta ", "Alpha", "alpha", "zeta", "Alpha"]) == [
        "Alpha",
        "alpha",
        "zeta",
    ]


def test_no_tags_is_the_empty_list():
    assert normalize_tags([]) == []


def test_case_is_kept():
    assert normalize_tags(["WA LCB"]) == ["WA LCB"]


@pytest.mark.parametrize("tag", ["", "   ", "\t"])
def test_an_empty_tag_is_refused(tag):
    with pytest.raises(TagError, match="empty"):
        normalize_tags(["ok", tag])


def test_a_tag_at_the_length_limit_is_kept_and_one_over_is_refused():
    assert normalize_tags(["x" * MAX_TAG_LENGTH]) == ["x" * MAX_TAG_LENGTH]
    with pytest.raises(TagError, match="255"):
        normalize_tags(["x" * (MAX_TAG_LENGTH + 1)])


def test_the_length_limit_is_measured_after_stripping():
    assert normalize_tags([" " + "x" * MAX_TAG_LENGTH + " "]) == ["x" * MAX_TAG_LENGTH]


def test_a_comma_is_refused():
    with pytest.raises(TagError, match="comma"):
        normalize_tags(["a,b"])


@pytest.mark.parametrize("tag", ["a\nb", "a\x00b", "a\x1fb", "a\x7fb", "a\tb"])
def test_an_inner_control_character_is_refused(tag):
    with pytest.raises(TagError, match="control"):
        normalize_tags([tag])


def test_a_non_string_is_refused():
    with pytest.raises(TagError, match="string"):
        normalize_tags(["ok", 7])


def test_thirty_two_tags_are_kept_and_thirty_three_refused():
    tags = [f"t{n:02d}" for n in range(MAX_TAGS)]
    assert normalize_tags(tags) == tags
    with pytest.raises(TagError, match="32"):
        normalize_tags([*tags, "one-more"])


def test_the_count_limit_is_measured_after_deduplication():
    tags = [f"t{n:02d}" for n in range(MAX_TAGS)]
    assert normalize_tags([*tags, *tags]) == tags


def test_every_problem_is_reported_with_its_position():
    with pytest.raises(TagError) as refused:
        normalize_tags(["ok", "", "a,b"])
    assert [p.index for p in refused.value.problems] == [1, 2]


def test_split_tags_splits_on_commas_and_drops_blank_pieces():
    """The dashboard input, as Watcher's editor read it: blank pieces are not tags."""
    assert split_tags(" a, b ,, ,c ") == ["a", "b", "c"]
    assert split_tags(" , ") == []


# --- the writes ---


async def _item(session, tags=None) -> InfoItem:
    item = InfoItem(name="Tagged", **({"tags": tags} if tags is not None else {}))
    session.add(item)
    await session.flush()
    return item


async def test_a_new_item_has_no_tags(session):
    item = await _item(session)
    await session.refresh(item)
    assert item.tags == []


async def test_set_tags_replaces_the_whole_set(session):
    item = await _item(session, ["old", "keep"])

    out = await set_tags(session, item.info_item_id, ["keep", " new "])

    assert out.tags == ["keep", "new"]


async def test_set_tags_refuses_and_stores_nothing(session):
    item = await _item(session, ["old"])

    with pytest.raises(TagError):
        await set_tags(session, item.info_item_id, ["a,b"])

    await session.refresh(item)
    assert item.tags == ["old"]


async def test_set_tags_on_a_missing_item_raises(session):
    with pytest.raises(InfoItemNotFoundError):
        await set_tags(session, ULID(), ["a"])


async def test_add_tags_merges_into_the_stored_set(session):
    item = await _item(session, ["b"])

    out = await add_tags(session, item.info_item_id, ["c", "a", "b"])

    assert out.tags == ["a", "b", "c"]


async def test_add_tags_past_the_count_limit_is_refused(session):
    item = await _item(session, [f"t{n:02d}" for n in range(MAX_TAGS)])

    with pytest.raises(TagError, match="32"):
        await add_tags(session, item.info_item_id, ["one-more"])


async def test_remove_tag_drops_exactly_that_tag(session):
    item = await _item(session, ["Alpha", "alpha"])

    out = await remove_tag(session, item.info_item_id, "alpha")

    assert out.tags == ["Alpha"]


async def test_removing_a_tag_the_item_lacks_changes_nothing(session):
    item = await _item(session, ["a"])

    out = await remove_tag(session, item.info_item_id, "b")

    assert out.tags == ["a"]


async def test_add_and_remove_on_a_missing_item_raise(session):
    with pytest.raises(InfoItemNotFoundError):
        await add_tags(session, ULID(), ["a"])
    with pytest.raises(InfoItemNotFoundError):
        await remove_tag(session, ULID(), "a")


async def test_tags_are_allowed_on_an_archived_item(session):
    """D3: archive is watch-only (archiver#361)."""
    item = await _item(session)
    item.archived_at = item.created_at
    await session.flush()

    out = await set_tags(session, item.info_item_id, ["a"])

    assert out.tags == ["a"]


async def test_two_racing_adds_both_land(test_engine, committed_rows):
    """D4's lock: without it both read the same set and the second write drops
    the first's tag. Real connections and commits - a row lock is only visible
    across independent transactions."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as setup:
        item = InfoItem(name="racing tags", tags=["base"])
        setup.add(item)
        await setup.commit()
        item_id = item.info_item_id
        committed_rows.append((InfoItem, item_id))

    first_locked = asyncio.Event()

    async def _add(tag: str, *, hold: bool) -> None:
        async with factory() as s:
            await add_tags(s, item_id, [tag])
            if hold:
                first_locked.set()
                await asyncio.sleep(0.2)  # the second add must wait on the lock
            await s.commit()

    async def _second() -> None:
        await first_locked.wait()
        await _add("two", hold=False)

    await asyncio.gather(_add("one", hold=True), _second())

    async with factory() as check:
        stored = await check.get(InfoItem, item_id)
        assert stored.tags == ["base", "one", "two"]
