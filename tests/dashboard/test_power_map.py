"""GET /dashboard/power-map/orgs — the Organization row's type-ahead (archiver#306).

Under two characters it answers from orgs already linked on the item's
domains, with no Power Map call; from two up it searches Power Map. Power Map
dormant or down is a ``role="status"`` line in a 200, so the rest of the page
never notices.
"""

from datetime import UTC, datetime

import pytest

from src.api.deps import get_power_map
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource, PmOrganization
from src.core.power_map import PowerMapUnavailableError
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, FakePowerMap, org

_HEADERS = {"X-ExeDev-UserID": "ext-pm", "X-ExeDev-Email": "pm@example.com"}
_URL = "/dashboard/power-map/orgs"


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


async def _item_on(session, domain: str, name: str, pm_org_id: str | None = None) -> InfoItem:
    item = InfoItem(name=name, rep_fields={}, pm_org_id=pm_org_id)
    source = InfoSource(
        url=f"https://{domain}/{name.lower().replace(' ', '-')}",
        source_specs=[],
        domain_name=domain,
    )
    session.add_all([item, source])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()
    return item


async def _snapshot(session, pm_org_id: str, name: str, acronym: str | None) -> PmOrganization:
    row = PmOrganization(
        pm_org_id=pm_org_id,
        name=name,
        acronym=acronym,
        active=True,
        pm_updated_at=datetime.now(UTC),
        checked_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_unauthenticated_redirects(client, power_map):
    r = await client.get(_URL, params={"q": "wslcb"}, follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_two_characters_search_power_map(client, power_map):
    r = await client.get(_URL, params={"q": "ws"}, headers=_HEADERS)

    assert r.status_code == 200
    assert ("search_orgs", "ws", 10) in power_map.calls
    assert 'role="option"' in r.text
    assert f'data-pm-org-id="{WSLCB_ID}"' in r.text
    assert f"{WSLCB_NAME} (WSLCB)" in r.text
    assert r.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_no_hits_says_so(client, power_map):
    r = await client.get(_URL, params={"q": "zzz"}, headers=_HEADERS)

    assert 'role="option"' not in r.text
    assert "No Power Map organization matches" in r.text


@pytest.mark.asyncio
async def test_power_map_down_is_a_status_line_not_an_error(client, power_map):
    power_map.unavailable = PowerMapUnavailableError("request timed out")

    r = await client.get(_URL, params={"q": "wslcb"}, headers=_HEADERS)

    assert r.status_code == 200
    assert 'role="status"' in r.text
    assert "Power Map unavailable" in r.text
    assert 'role="option"' not in r.text


@pytest.mark.asyncio
async def test_dormant_power_map_is_a_status_line(client, no_power_map):
    r = await client.get(_URL, params={"q": "wslcb"}, headers=_HEADERS)

    assert r.status_code == 200
    assert 'role="status"' in r.text
    assert "Power Map not configured" in r.text


@pytest.mark.asyncio
async def test_under_two_characters_answers_locally_without_power_map(client, session, power_map):
    await _snapshot(session, WSLCB_ID, WSLCB_NAME, "WSLCB")
    await _item_on(session, "lcb.wa.gov", "Linked Sibling", pm_org_id=WSLCB_ID)
    item = await _item_on(session, "lcb.wa.gov", "Unlinked Item")

    r = await client.get(
        _URL, params={"q": "w", "item_id": str(item.info_item_id)}, headers=_HEADERS
    )

    assert power_map.calls == []
    assert f'data-pm-org-id="{WSLCB_ID}"' in r.text
    assert "Linked to 1 item on this domain" in r.text


@pytest.mark.asyncio
async def test_local_suggestions_stay_on_the_items_domains(client, session, power_map):
    await _snapshot(session, WSLCB_ID, WSLCB_NAME, "WSLCB")
    await _snapshot(session, "01JPM00000000000000000000O", "Oregon Liquor and Cannabis", "OLCC")
    await _item_on(session, "lcb.wa.gov", "WA Sibling", pm_org_id=WSLCB_ID)
    await _item_on(session, "oregon.gov", "OR Item", pm_org_id="01JPM00000000000000000000O")
    item = await _item_on(session, "lcb.wa.gov", "Unlinked WA Item")

    r = await client.get(
        _URL, params={"q": "", "item_id": str(item.info_item_id)}, headers=_HEADERS
    )

    assert WSLCB_ID in r.text
    assert "OLCC" not in r.text


@pytest.mark.asyncio
async def test_local_suggestions_leave_out_the_items_own_org(client, session, power_map):
    await _snapshot(session, WSLCB_ID, WSLCB_NAME, "WSLCB")
    await _item_on(session, "lcb.wa.gov", "Sibling", pm_org_id=WSLCB_ID)
    item = await _item_on(session, "lcb.wa.gov", "Already Linked", pm_org_id=WSLCB_ID)

    r = await client.get(
        _URL, params={"q": "", "item_id": str(item.info_item_id)}, headers=_HEADERS
    )

    assert 'role="option"' not in r.text


@pytest.mark.asyncio
async def test_under_two_characters_with_no_item_is_empty(client, power_map):
    r = await client.get(_URL, params={"q": "w"}, headers=_HEADERS)

    assert r.status_code == 200
    assert power_map.calls == []
    assert 'role="option"' not in r.text


@pytest.mark.asyncio
async def test_an_unknown_item_id_is_no_suggestions_not_an_error(client, power_map):
    r = await client.get(_URL, params={"q": "", "item_id": "not-a-ulid"}, headers=_HEADERS)

    assert r.status_code == 200
    assert 'role="option"' not in r.text


@pytest.mark.asyncio
async def test_a_hit_label_is_escaped(client, power_map):
    power_map.plant(org(pm_org_id="01JPM00000000000000000000X", name="<b>Bad</b> Board"))

    r = await client.get(_URL, params={"q": "bad"}, headers=_HEADERS)

    assert "<b>Bad</b>" not in r.text
    assert "&lt;b&gt;Bad&lt;/b&gt; Board" in r.text
