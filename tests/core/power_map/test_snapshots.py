"""pm_organizations writes and reads (archiver#304): apply_org_snapshot, load_org_values."""

from datetime import UTC, datetime

import pytest

from src.core.models import InfoItem, PmOrganization
from src.core.power_map import snapshots
from src.core.power_map.snapshots import (
    OrgUnnamedError,
    apply_org_snapshot,
    load_org_values,
    org_values,
)
from src.core.rep_fields import OrgValues
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, org

T0 = datetime(2026, 10, 6, 12, tzinfo=UTC)
T1 = datetime(2026, 10, 6, 13, tzinfo=UTC)


@pytest.mark.asyncio
async def test_first_apply_inserts_the_snapshot(session):
    row = await apply_org_snapshot(session, org(), now=T0)

    assert row.pm_org_id == WSLCB_ID
    assert row.name == WSLCB_NAME
    assert row.acronym == "WSLCB"
    assert row.active is True
    assert row.etag == '"v1"'
    assert row.checked_at == T0
    assert row.renamed_from is None
    assert row.renamed_at is None


@pytest.mark.asyncio
async def test_reapplying_the_same_values_only_moves_checked_at(session):
    await apply_org_snapshot(session, org(), now=T0)
    row = await apply_org_snapshot(session, org(), now=T1)

    assert row.checked_at == T1
    assert row.renamed_from is None


@pytest.mark.asyncio
async def test_a_changed_name_records_the_rename(session, monkeypatch):
    # A spy, not caplog: configure_logging() stops propagation once any test
    # has run the app lifespan.
    warnings: list[str] = []
    monkeypatch.setattr(snapshots.logger, "warning", lambda msg, **kw: warnings.append(msg))
    await apply_org_snapshot(session, org(), now=T0)
    row = await apply_org_snapshot(session, org(name="WA Cannabis Board", etag='"v2"'), now=T1)

    assert row.name == "WA Cannabis Board"
    assert row.renamed_from == WSLCB_NAME
    assert row.renamed_at == T1
    assert row.etag == '"v2"'
    assert warnings == ["pm_org_renamed"]


@pytest.mark.asyncio
async def test_a_changed_acronym_is_a_rename_too(session):
    await apply_org_snapshot(session, org(), now=T0)
    row = await apply_org_snapshot(session, org(acronym="LCB"), now=T1)

    assert row.acronym == "LCB"
    assert row.renamed_from == WSLCB_NAME
    assert row.renamed_at == T1


@pytest.mark.asyncio
async def test_an_answer_clears_missing_since(session):
    row = await apply_org_snapshot(session, org(), now=T0)
    row.missing_since = T0
    await session.flush()

    row = await apply_org_snapshot(session, org(), now=T1)

    assert row.missing_since is None


@pytest.mark.asyncio
async def test_an_org_with_no_name_cannot_be_snapshotted(session):
    with pytest.raises(OrgUnnamedError):
        await apply_org_snapshot(session, org(name=None), now=T0)
    assert await session.get(PmOrganization, WSLCB_ID) is None


@pytest.mark.asyncio
async def test_org_values_reads_name_and_acronym():
    row = PmOrganization(pm_org_id=WSLCB_ID, name="N", acronym=None)
    assert org_values(row) == OrgValues(name="N", acronym=None)
    assert org_values(None) is None


@pytest.mark.asyncio
async def test_load_org_values_follows_the_items_link(session):
    await apply_org_snapshot(session, org(), now=T0)
    linked = InfoItem(name="linked", pm_org_id=WSLCB_ID)
    unlinked = InfoItem(name="unlinked")
    session.add_all([linked, unlinked])
    await session.flush()

    assert await load_org_values(session, linked) == OrgValues(name=WSLCB_NAME, acronym="WSLCB")
    assert await load_org_values(session, unlinked) is None
