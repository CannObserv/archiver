"""The Overview's Organization row: view, link, unlink, confirm (archiver#306).

Link and unlink go through ``link_org``, the write ``PUT /info-items/{id}/org``
shares. A link that would move an active assignment's path is a 409 showing
before → after, confirmed by re-sending the same org with
``allow_destination_change``: #302's move contract. A success answers with the
row and fires ``replicationChanged`` from ``org``, so the Replication blocks
re-read the effective bag.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.api.deps import get_power_map
from src.api.main import app
from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    PmOrganization,
    RepSpec,
)
from src.core.power_map import PowerMapUnavailableError
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, FakePowerMap, org
from tests.dashboard.conftest import read_flash

_HEADERS = {"X-ExeDev-UserID": "ext-org", "X-ExeDev-Email": "org@example.com"}
_ORG_PATH = "organizations/{org.title_slug}/{source_revision.id}.html"
_WSLCB_SLUG = "washington_state_liquor_and_cannabis_board"


@pytest.fixture
def power_map():
    pm = FakePowerMap(org())
    app.dependency_overrides[get_power_map] = lambda: pm
    yield pm
    app.dependency_overrides.pop(get_power_map, None)


@pytest.fixture
def no_power_map():
    app.dependency_overrides[get_power_map] = lambda: None
    yield
    app.dependency_overrides.pop(get_power_map, None)


async def _item(session, bag: dict | None = None, *, spec: RepSpec | None = None) -> InfoItem:
    item = InfoItem(name="Org Row Item", rep_fields=bag or {})
    session.add(item)
    if spec is not None:
        session.add(spec)
    await session.flush()
    if spec is not None:
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
        await session.flush()
    return item


def _spec() -> RepSpec:
    return RepSpec(
        provider="gcs",
        name="Org Layout",
        schema_version=1,
        document={
            "provider": "gcs",
            "version": 1,
            "credentials_alias": "default",
            "bucket": "test-bucket",
            "required_fields": ["org.title_slug"],
            "path_template": _ORG_PATH,
        },
    )


async def _snapshot(session, item: InfoItem | None = None, **overrides) -> PmOrganization:
    values = {
        "pm_org_id": WSLCB_ID,
        "name": WSLCB_NAME,
        "acronym": "WSLCB",
        "active": True,
        "pm_updated_at": datetime.now(UTC),
        "checked_at": datetime.now(UTC),
    }
    values.update(overrides)
    row = PmOrganization(**values)
    session.add(row)
    await session.flush()
    if item is not None:
        item.pm_org_id = row.pm_org_id
        await session.flush()
    return row


def _detail(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}"


def _org_url(item: InfoItem) -> str:
    return f"/dashboard/info-items/{item.info_item_id}/org"


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unlinked_item_says_not_linked(client, session, power_map):
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert r.status_code == 200
    assert 'id="ii-org"' in r.text
    assert "Not linked" in r.text
    assert 'role="combobox"' in r.text


@pytest.mark.asyncio
async def test_a_linked_item_shows_name_and_acronym(client, session, power_map):
    item = await _item(session)
    await _snapshot(session, item)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert f"{WSLCB_NAME} (WSLCB)" in r.text
    assert "Not linked" not in r.text
    assert "Unlink keeps current paths; the values become hand-typed." in r.text


@pytest.mark.asyncio
async def test_a_recent_rename_is_a_notice_with_the_new_path(client, session, power_map):
    item = await _item(session)
    await _snapshot(
        session,
        item,
        renamed_from="WA Liquor Control Board",
        renamed_at=datetime.now(UTC) - timedelta(days=2),
    )

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "Renamed" in r.text
    assert "was WA Liquor Control Board" in r.text
    assert f"organizations/{_WSLCB_SLUG}/…" in r.text


@pytest.mark.parametrize(
    ("overrides", "word"),
    [
        ({"archived_at": datetime(2026, 9, 1, tzinfo=UTC)}, "Archived in Power Map"),
        ({"active": False}, "Inactive in Power Map"),
        ({"missing_since": datetime(2026, 10, 1, tzinfo=UTC)}, "Missing from Power Map since"),
        ({"succeeded_by": "01JPM00000000000000000000S"}, "Succeeded by 01JPM00000000000000000000S"),
    ],
)
@pytest.mark.asyncio
async def test_each_power_map_state_is_a_worded_notice(client, session, power_map, overrides, word):
    item = await _item(session)
    await _snapshot(session, item, **overrides)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert word in r.text


@pytest.mark.asyncio
async def test_a_successor_archiver_holds_is_named(client, session, power_map):
    await _snapshot(session, pm_org_id="01JPM00000000000000000000S", name="WA Cannabis Commission")
    item = await _item(session)
    await _snapshot(session, item, succeeded_by="01JPM00000000000000000000S")

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "Succeeded by WA Cannabis Commission" in r.text


@pytest.mark.asyncio
async def test_a_recent_merge_names_the_org_folded_in(client, session, power_map):
    item = await _item(session)
    await _snapshot(session, item)
    await _snapshot(
        session,
        pm_org_id="01JPM00000000000000000000L",
        name="Liquor Control Board",
        merged_into=WSLCB_ID,
        checked_at=datetime.now(UTC) - timedelta(days=1),
    )
    await _snapshot(
        session,
        pm_org_id="01JPM00000000000000000000M",
        name="Long Ago Board",
        merged_into=WSLCB_ID,
        checked_at=datetime.now(UTC) - timedelta(days=90),
    )

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "Liquor Control Board was merged into this org" in r.text
    assert "Long Ago Board" not in r.text


@pytest.mark.asyncio
async def test_dormant_power_map_says_so_where_the_search_would_be(client, session, no_power_map):
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert r.status_code == 200
    assert "Power Map not configured" in r.text
    assert 'role="combobox"' not in r.text


@pytest.mark.asyncio
async def test_dormant_power_map_still_offers_unlink(client, session, no_power_map):
    item = await _item(session)
    await _snapshot(session, item)

    r = await client.get(_detail(item), headers=_HEADERS)

    assert "Unlink" in r.text


@pytest.mark.asyncio
async def test_the_combobox_opens_on_local_suggestions(client, session, power_map):
    await _snapshot(session)
    sibling = await _item(session)
    item = await _item(session)
    for it in (sibling, item):
        source = InfoSource(
            url=f"https://lcb.wa.gov/{it.info_item_id}", source_specs=[], domain_name="lcb.wa.gov"
        )
        session.add(source)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=it.info_item_id, info_source_id=source.info_source_id)
        )
    sibling.pm_org_id = WSLCB_ID
    await session.flush()

    r = await client.get(_detail(item), headers=_HEADERS)

    assert f'data-pm-org-id="{WSLCB_ID}"' in r.text
    assert power_map.calls == []


# ---------------------------------------------------------------------------
# Link / unlink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_swaps_the_row_and_tells_the_replication_blocks(client, session, power_map):
    item = await _item(session, {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}})

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID})

    assert r.status_code == 200, r.text
    assert r.headers["HX-Retarget"] == "#ii-org"
    assert r.headers["HX-Reswap"] == "outerHTML"
    triggers = read_flash(r)
    assert triggers["replicationChanged"] == {"source": "org"}
    assert triggers["showFlash"]["level"] == "success"
    assert f"{WSLCB_NAME} (WSLCB)" in r.text
    assert "ii-org-heading" in r.text  # the swapped row moves focus to its label
    await session.refresh(item)
    assert item.pm_org_id == WSLCB_ID
    assert item.rep_fields == {}


@pytest.mark.asyncio
async def test_unlink_writes_the_values_back_and_moves_nothing(client, session, power_map):
    item = await _item(session, spec=_spec())
    await _snapshot(session, item)

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": ""})

    assert r.status_code == 200, r.text
    assert "Not linked" in r.text
    assert read_flash(r)["replicationChanged"] == {"source": "org"}
    await session.refresh(item)
    assert item.pm_org_id is None
    assert item.rep_fields == {"org": {"title": WSLCB_NAME, "acronym": "WSLCB"}}
    assert power_map.calls == []


@pytest.mark.asyncio
async def test_unlink_works_with_power_map_dormant(client, session, no_power_map):
    item = await _item(session)
    await _snapshot(session, item)

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": ""})

    assert r.status_code == 200, r.text
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_a_link_that_moves_paths_shows_the_diff_and_waits(client, session, power_map):
    item = await _item(session, {"org": {"title": "WA LCB"}}, spec=_spec())

    r = await client.put(
        _org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID, "q": "WSLCB label"}
    )

    assert r.status_code == 409
    assert "Not linked yet: linking WSLCB label changes" in r.text
    assert "organizations/wa_lcb/" in r.text
    assert f"organizations/{_WSLCB_SLUG}/" in r.text
    assert "Org Layout" in r.text
    assert "Link and move" in r.text
    assert "HX-Trigger" not in r.headers
    await session.refresh(item)
    assert item.pm_org_id is None
    assert item.rep_fields == {"org": {"title": "WA LCB"}}


@pytest.mark.asyncio
async def test_link_and_move_resends_the_org_it_warned_about(client, session, power_map):
    item = await _item(session, {"org": {"title": "WA LCB"}}, spec=_spec())
    warned = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID})

    vals = json.loads(_attr(warned.text, "hx-vals"))
    assert vals == {"pm_org_id": WSLCB_ID, "allow_destination_change": "true", "q": WSLCB_ID}
    assert _attr(warned.text, "hx-put") == _org_url(item)

    r = await client.put(_org_url(item), headers=_HEADERS, data=vals)

    assert r.status_code == 200, r.text
    await session.refresh(item)
    assert item.pm_org_id == WSLCB_ID


@pytest.mark.asyncio
async def test_power_map_down_links_nothing_and_says_so(client, session, power_map):
    power_map.unavailable = PowerMapUnavailableError("request timed out")
    item = await _item(session)

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID})

    assert r.status_code == 503
    assert "Power Map unavailable" in r.text
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_link_with_power_map_dormant_says_not_configured(client, session, no_power_map):
    item = await _item(session)

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID})

    assert r.status_code == 503
    assert "Power Map not configured" in r.text


@pytest.mark.asyncio
async def test_an_org_power_map_does_not_have_is_refused(client, session, power_map):
    item = await _item(session)

    r = await client.put(
        _org_url(item), headers=_HEADERS, data={"pm_org_id": "01JPM00000000000000000000Z"}
    )

    assert r.status_code == 422
    assert "no such organization" in r.text


@pytest.mark.asyncio
async def test_a_link_that_breaks_an_assignment_names_it(client, session, power_map):
    spec = _spec()
    spec.document = {**spec.document, "required_fields": ["org.acronym_slug"]}
    power_map.plant(org(acronym=None))
    item = await _item(session, {"org": {"title": "WA LCB", "acronym": "WSLCB"}}, spec=spec)

    r = await client.put(_org_url(item), headers=_HEADERS, data={"pm_org_id": WSLCB_ID})

    assert r.status_code == 422
    assert "RepSpec &#39;Org Layout&#39;: required field org.acronym_slug" in r.text
    await session.refresh(item)
    assert item.pm_org_id is None


@pytest.mark.asyncio
async def test_the_row_form_targets_its_flash_for_every_refusal(client, session, power_map):
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    form = r.text[r.text.index('id="ii-org-form"') :]
    form = form[: form.index(">")]
    for status in ("409", "422", "503"):
        assert f'hx-target-{status}="#ii-org-flash"' in form


@pytest.mark.asyncio
async def test_link_of_a_missing_item_is_404(client, power_map):
    r = await client.put(
        "/dashboard/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ/org",
        headers=_HEADERS,
        data={"pm_org_id": WSLCB_ID},
    )

    assert r.status_code == 404


def _attr(html: str, name: str) -> str:
    """The first ``name='…'`` or ``name="…"`` attribute value, unescaped."""
    start = html.index(f"{name}=") + len(name) + 1
    quote = html[start]
    end = html.index(quote, start + 1)
    return (
        html[start + 1 : end]
        .replace("&#34;", '"')
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&amp;", "&")
    )


@pytest.mark.asyncio
async def test_the_rows_flash_is_named_to_the_combobox(client, session, power_map):
    """CR 1: the component clears this flash when the choice changes or Cancel."""
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    form = r.text[r.text.index('id="ii-org-form"') :]
    assert 'data-flash="ii-org-flash"' in form[: form.index(">")]


@pytest.mark.asyncio
async def test_the_combobox_has_one_persistent_live_region(client, session, power_map):
    """CR 7: outside the swap target, so it exists before anything is said in it."""
    item = await _item(session)

    r = await client.get(_detail(item), headers=_HEADERS)

    form = r.text[r.text.index('id="ii-org-form"') :]
    form = form[: form.index("</form>")]
    results = form[form.index('id="ii-org-results"') :]
    results = results[: results.index("</div>")]
    assert 'role="status"' not in results
    assert '<p role="status" class="sr-only" x-ref="live"></p>' in form
