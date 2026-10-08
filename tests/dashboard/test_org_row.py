"""The Overview's Organization row: what it says about a linked org (archiver#306).

Pure: the route loads the snapshot row, the successor's name and the merge
losers, so each notice is tested here without a database.
"""

from datetime import UTC, datetime, timedelta

from src.core.models import PmOrganization
from src.core.power_map import OrgHit
from src.dashboard.org_row import (
    RECENT_DAYS,
    build_org_row,
    option_from_hit,
)

_NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
_ID = "01JPM00000000000000000000A"


def _org(**overrides) -> PmOrganization:
    values = {
        "pm_org_id": _ID,
        "name": "Washington State Liquor and Cannabis Board",
        "acronym": "WSLCB",
        "archived_at": None,
        "active": True,
        "succeeded_by": None,
        "merged_into": None,
        "renamed_from": None,
        "renamed_at": None,
        "missing_since": None,
        "pm_updated_at": _NOW,
        "checked_at": _NOW,
    }
    values.update(overrides)
    return PmOrganization(**values)


def _kinds(row) -> list[str]:
    return [n.kind for n in row.notices]


def test_an_unlinked_item_has_no_org_and_no_notices():
    row = build_org_row(None, bag={}, now=_NOW)

    assert row.linked is False
    assert row.notices == ()


def test_a_current_org_reads_name_and_acronym_with_no_notices():
    row = build_org_row(_org(), bag={}, now=_NOW)

    assert row.linked is True
    assert row.label == "Washington State Liquor and Cannabis Board (WSLCB)"
    assert row.notices == ()


def test_an_org_with_no_acronym_is_labelled_by_name_alone():
    row = build_org_row(_org(acronym=None), bag={}, now=_NOW)

    assert row.label == "Washington State Liquor and Cannabis Board"


def test_a_recent_rename_names_the_old_name_and_the_new_path():
    row = build_org_row(
        _org(name="WA Cannabis Board", renamed_from="WA LCB", renamed_at=_NOW - timedelta(days=3)),
        bag={},
        now=_NOW,
    )

    (notice,) = row.notices
    assert notice.kind == "renamed"
    assert "was WA LCB" in notice.text
    assert "organizations/wa_cannabis_board/…" in notice.text


def test_the_renamed_path_honours_a_stored_title_slug_override():
    """The notice states the path the item renders, not the one the name alone would."""
    row = build_org_row(
        _org(name="WA Cannabis Board", renamed_from="WA LCB", renamed_at=_NOW - timedelta(days=3)),
        bag={"org": {"title_slug": "wslcb"}},
        now=_NOW,
    )

    assert "organizations/wslcb/…" in row.notices[0].text


def test_a_rename_to_a_name_with_no_slug_states_no_path():
    """CR 4: was "paths now organizations/None/…" - a path that does not exist."""
    row = build_org_row(
        _org(name="!!!", renamed_from="WA LCB", renamed_at=_NOW - timedelta(days=1)),
        bag={},
        now=_NOW,
    )

    (notice,) = row.notices
    assert notice.text == "was WA LCB"


def test_a_rename_older_than_the_window_is_no_longer_news():
    row = build_org_row(
        _org(renamed_from="WA LCB", renamed_at=_NOW - timedelta(days=RECENT_DAYS, seconds=1)),
        bag={},
        now=_NOW,
    )

    assert row.notices == ()


def test_each_power_map_state_has_its_own_worded_notice():
    row = build_org_row(
        _org(
            archived_at=_NOW - timedelta(days=1),
            active=False,
            succeeded_by="01JPM00000000000000000000B",
            missing_since=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        bag={},
        now=_NOW,
        successor_name="Washington Cannabis Commission",
    )

    assert _kinds(row) == ["succeeded", "archived", "inactive", "missing"]
    texts = {n.kind: n.text for n in row.notices}
    assert "Succeeded by Washington Cannabis Commission" in texts["succeeded"]
    assert "Archived" in texts["archived"]
    assert "Inactive" in texts["inactive"]
    assert "Missing from Power Map since 2026-10-01" in texts["missing"]


def test_a_successor_archiver_has_not_seen_is_named_by_its_id():
    row = build_org_row(_org(succeeded_by="01JPM00000000000000000000B"), bag={}, now=_NOW)

    assert "Succeeded by 01JPM00000000000000000000B" in row.notices[0].text


def test_a_recent_merge_names_the_org_folded_in():
    row = build_org_row(_org(), bag={}, now=_NOW, merged_from=("Liquor Control Board",))

    (notice,) = row.notices
    assert notice.kind == "merged"
    assert "Liquor Control Board" in notice.text


def test_every_notice_carries_a_word_not_only_a_colour():
    row = build_org_row(
        _org(
            renamed_from="Old",
            renamed_at=_NOW,
            archived_at=_NOW,
            active=False,
            succeeded_by="x",
            missing_since=_NOW,
        ),
        bag={},
        now=_NOW,
        merged_from=("Loser",),
    )

    assert len(row.notices) == 6
    for notice in row.notices:
        assert notice.label and notice.label[0].isupper()
        assert notice.level in ("info", "warning", "danger")


def test_a_search_hit_becomes_an_option_labelled_like_the_row():
    option = option_from_hit(
        OrgHit(
            pm_org_id=_ID,
            name="Washington State Liquor and Cannabis Board",
            acronym="WSLCB",
            archived_at=None,
            succeeded_by=None,
        )
    )

    assert option.pm_org_id == _ID
    assert option.label == "Washington State Liquor and Cannabis Board (WSLCB)"
    assert option.hint is None


def test_a_superseded_hit_says_so_before_it_is_chosen():
    option = option_from_hit(
        OrgHit(pm_org_id=_ID, name="Old Board", acronym=None, archived_at=None, succeeded_by="B")
    )

    assert option.label == "Old Board"
    assert option.hint == "Succeeded by another org in Power Map"


def test_an_unnamed_hit_is_labelled_by_its_id():
    option = option_from_hit(
        OrgHit(pm_org_id=_ID, name=None, acronym=None, archived_at=None, succeeded_by=None)
    )

    assert option.label == _ID
