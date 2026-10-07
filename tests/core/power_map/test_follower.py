"""The Power Map org follower (archiver#305): one conditional GET per linked org.

``refresh_linked_orgs`` walks every ``pm_organizations`` row an item links and
applies Power Map's answer: 304 records the check, 200 goes through
``apply_org_snapshot`` (a rename moves paths without confirmation, logged per
assignment), a merge re-points the items at the winner, a gone org is marked
missing and keeps rendering. No answer changes nothing.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    PmOrganization,
    RepSpec,
    SourceRevision,
)
from src.core.power_map import PowerMapUnavailableError, follower
from src.core.power_map.follower import (
    MERGED,
    MISSING,
    NOT_MODIFIED,
    RENAMED,
    UNAVAILABLE,
    UNNAMED,
    UPDATED,
    main,
    refresh_linked_orgs,
)
from src.core.power_map.snapshots import apply_org_snapshot
from src.core.services.replication_issuance import issue_for_revision
from src.core.tools import set_rep_fields
from src.core.tools.rep_fields_gate import lock_info_item
from tests.core.power_map.fake import WSLCB_ID, WSLCB_NAME, FakePowerMap, org

WINNER_ID = "01JPM00000000000000000000W"
OTHER_ID = "01JPM00000000000000000000C"
T0 = datetime(2026, 10, 6, 12, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 12, tzinfo=UTC)
_ORG_PATH = "organizations/{org.title_slug}/{source_revision.fingerprint}.html"


class _Spy:
    """Collects ``(message, extra)`` from a logger method: caplog misses once
    ``configure_logging()`` has stopped propagation."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def __call__(self, message: str, *args, extra: dict | None = None, **kwargs) -> None:
        self.records.append((message, extra or {}))

    @property
    def messages(self) -> list[str]:
        return [m for m, _ in self.records]


class _Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def warnings(monkeypatch) -> _Spy:
    spy = _Spy()
    monkeypatch.setattr(follower.logger, "warning", spy)
    return spy


@pytest.fixture
def move_warnings(monkeypatch) -> _Spy:
    spy = _Spy()
    monkeypatch.setattr(set_rep_fields.logger, "warning", spy)
    return spy


async def _linked_item(session, pm_org_id: str = WSLCB_ID, *, assigned: bool = False) -> InfoItem:
    item = InfoItem(name=f"linked-{ULID()}", rep_fields={}, pm_org_id=pm_org_id)
    session.add(item)
    await session.flush()
    if assigned:
        spec = RepSpec(
            provider="gcs",
            name=f"spec-{ULID()}",
            schema_version=1,
            document={
                "provider": "gcs",
                "credentials_alias": "gcs-cannobserv-prod",
                "path_template": _ORG_PATH,
                "required_fields": ["org.title_slug"],
                "object_options": {"storage_class": "STANDARD"},
            },
        )
        session.add(spec)
        await session.flush()
        session.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=datetime.now(UTC),
            )
        )
        await session.flush()
    return item


async def _snapshot(session, snapshot=None) -> None:
    await apply_org_snapshot(session, snapshot or org(), now=T0)


async def _refresh(session, pm: FakePowerMap, **kwargs) -> dict[str, str]:
    kwargs.setdefault("pace_seconds", 0)
    return await refresh_linked_orgs(session, pm, **kwargs)


async def _row(session, pm_org_id: str = WSLCB_ID) -> PmOrganization:
    row = await session.get(PmOrganization, pm_org_id, populate_existing=True)
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# One test per outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_modified_records_the_check(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(org())

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: NOT_MODIFIED}
    assert pm.calls == [("get_org", WSLCB_ID, '"v1"')]
    row = await _row(session)
    assert row.checked_at > T0
    assert row.name == WSLCB_NAME


@pytest.mark.asyncio
async def test_a_200_mirrors_the_non_name_fields(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(
        org(
            active=False,
            archived_at=T1,
            succeeded_by=OTHER_ID,
            pm_updated_at=T1,
            etag='"v2"',
        )
    )

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: UPDATED}
    row = await _row(session)
    assert (row.active, row.archived_at, row.succeeded_by, row.etag) == (
        False,
        T1,
        OTHER_ID,
        '"v2"',
    )
    assert row.renamed_from is None


@pytest.mark.asyncio
async def test_a_succeeded_by_is_mirrored_never_followed(session):
    await _snapshot(session)
    item = await _linked_item(session)
    pm = FakePowerMap(org(succeeded_by=OTHER_ID, pm_updated_at=T1, etag='"v2"'))

    await _refresh(session, pm)

    await session.refresh(item)
    assert item.pm_org_id == WSLCB_ID
    assert [c[1] for c in pm.calls] == [WSLCB_ID]


@pytest.mark.asyncio
async def test_a_rename_records_renamed_from_and_logs_each_move(session, move_warnings):
    await _snapshot(session)
    item = await _linked_item(session, assigned=True)
    pm = FakePowerMap(org(name="WA Cannabis Board", pm_updated_at=T1, etag='"v2"'))

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: RENAMED}
    row = await _row(session)
    assert row.name == "WA Cannabis Board"
    assert row.renamed_from == WSLCB_NAME
    assert row.renamed_at is not None
    ((message, extra),) = move_warnings.records
    assert "rename" in message
    assert extra["info_item_id"] == str(item.info_item_id)
    (move,) = extra["moves"]
    assert move["before"].startswith("organizations/washington_state_liquor_and_cannabis_board/")
    assert move["after"].startswith("organizations/wa_cannabis_board/")


@pytest.mark.asyncio
async def test_a_rename_that_cannot_render_still_applies_and_warns(session, warnings):
    """CR 5: applied without confirmation (Q4), but said out loud now rather
    than at the next occasion's skip - and never a crash of the sweep."""
    await _snapshot(session)
    item = await _linked_item(session, assigned=True)
    pm = FakePowerMap(org(name="!!!", pm_updated_at=T1, etag='"v2"'))

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: RENAMED}
    assert (await _row(session)).name == "!!!"
    (extra,) = [e for m, e in warnings.records if "cannot render" in m]
    assert extra["info_item_id"] == str(item.info_item_id)
    (refusal,) = extra["refusals"]
    assert refusal["code"] == "rep_fields_unrenderable"


@pytest.mark.asyncio
async def test_an_assignment_broken_before_the_change_is_not_blamed_on_it(session, warnings):
    """CR 10: only an assignment the org change broke is warned about."""
    await _snapshot(session)
    item = await _linked_item(session, assigned=True)
    item.rep_fields = {"info_item": {"name": "!!!"}}
    ((_, spec),) = await set_rep_fields.active_assignments(session, item.info_item_id)
    spec.document = {**spec.document, "required_fields": ["org.title_slug", "info_item.name_slug"]}
    await session.flush()
    pm = FakePowerMap(org(name="WA Cannabis Board", pm_updated_at=T1, etag='"v2"'))

    assert await _refresh(session, pm) == {WSLCB_ID: RENAMED}

    assert not [m for m in warnings.messages if "cannot render" in m]


@pytest.mark.asyncio
async def test_a_merge_repoints_items_and_keeps_the_loser(session, warnings, move_warnings):
    await _snapshot(session)
    first = await _linked_item(session, assigned=True)
    second = await _linked_item(session)
    pm = FakePowerMap(org(WINNER_ID, name="WA Cannabis Board", etag='"w1"'))
    pm.merged[WSLCB_ID] = WINNER_ID

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: MERGED}
    for item in (first, second):
        await session.refresh(item)
        assert item.pm_org_id == WINNER_ID
    loser = await _row(session)
    assert loser.merged_into == WINNER_ID
    assert loser.name == WSLCB_NAME
    winner = await _row(session, WINNER_ID)
    assert winner.name == "WA Cannabis Board"
    assert winner.etag == '"w1"'
    assert "pm_org_merged" in warnings.messages
    ((_, extra),) = move_warnings.records
    assert extra["info_item_id"] == str(first.info_item_id)


@pytest.mark.asyncio
async def test_a_merge_whose_winner_is_gone_reads_as_missing(session):
    await _snapshot(session)
    item = await _linked_item(session)
    pm = FakePowerMap()
    pm.merged[WSLCB_ID] = WINNER_ID

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: MISSING}
    await session.refresh(item)
    assert item.pm_org_id == WSLCB_ID
    row = await _row(session)
    assert row.missing_since is not None
    assert row.merged_into is None


@pytest.mark.asyncio
async def test_a_gone_org_is_missing_and_keeps_its_snapshot(session, warnings):
    await _snapshot(session)
    await _linked_item(session)

    outcomes = await _refresh(session, FakePowerMap())

    assert outcomes == {WSLCB_ID: MISSING}
    row = await _row(session)
    assert row.missing_since is not None
    assert row.name == WSLCB_NAME
    assert row.etag == '"v1"'
    assert "pm_org_missing" in warnings.messages


@pytest.mark.asyncio
async def test_missing_since_keeps_the_first_miss(session, warnings):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap()

    await _refresh(session, pm)
    first = (await _row(session)).missing_since
    await _refresh(session, pm)

    assert (await _row(session)).missing_since == first
    assert warnings.messages.count("pm_org_missing") == 1


@pytest.mark.asyncio
async def test_a_missing_org_that_answers_again_clears_missing_since(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap()
    await _refresh(session, pm)

    pm.plant(org(pm_updated_at=T1, etag='"v2"'))
    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: UPDATED}
    assert (await _row(session)).missing_since is None


@pytest.mark.asyncio
async def test_unavailable_changes_nothing(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(org(name="Renamed", pm_updated_at=T1, etag='"v2"'))
    pm.unavailable = PowerMapUnavailableError("unexpected HTTP 503")

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: UNAVAILABLE}
    row = await _row(session)
    assert (row.name, row.checked_at, row.missing_since) == (WSLCB_NAME, T0, None)


@pytest.mark.asyncio
async def test_an_unnamed_org_writes_nothing(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(org(name=None, pm_updated_at=T1, etag='"v2"'))

    outcomes = await _refresh(session, pm)

    assert outcomes == {WSLCB_ID: UNNAMED}
    row = await _row(session)
    assert (row.name, row.etag, row.checked_at) == (WSLCB_NAME, '"v1"', T0)


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_runs_are_idempotent(session):
    await _snapshot(session)
    item = await _linked_item(session, assigned=True)
    pm = FakePowerMap(org(name="WA Cannabis Board", pm_updated_at=T1, etag='"v2"'))

    assert await _refresh(session, pm) == {WSLCB_ID: RENAMED}
    renamed_at = (await _row(session)).renamed_at
    assert await _refresh(session, pm) == {WSLCB_ID: NOT_MODIFIED}

    row = await _row(session)
    assert (row.name, row.renamed_from, row.renamed_at) == (
        "WA Cannabis Board",
        WSLCB_NAME,
        renamed_at,
    )
    await session.refresh(item)
    assert item.pm_org_id == WSLCB_ID


@pytest.mark.asyncio
async def test_a_merge_is_idempotent(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(org(WINNER_ID, name="WA Cannabis Board", etag='"w1"'))
    pm.merged[WSLCB_ID] = WINNER_ID

    await _refresh(session, pm)
    assert await _refresh(session, pm) == {WINNER_ID: NOT_MODIFIED}


@pytest.mark.asyncio
async def test_only_orgs_an_item_links_are_checked(session):
    await _snapshot(session)
    await _snapshot(session, org(OTHER_ID, name="Unlinked"))
    await _linked_item(session)
    pm = FakePowerMap(org())

    await _refresh(session, pm)

    assert [c[1] for c in pm.calls] == [WSLCB_ID]


@pytest.mark.asyncio
async def test_a_429_backs_off_for_retry_after_then_retries(session):
    await _snapshot(session)
    await _linked_item(session)
    pm = FakePowerMap(org())
    pm.failures.append(PowerMapUnavailableError("rate limited (HTTP 429)", retry_after=7))
    sleeps = _Sleeps()

    outcomes = await _refresh(session, pm, sleep=sleeps)

    assert outcomes == {WSLCB_ID: NOT_MODIFIED}
    assert sleeps.calls == [7]
    assert len(pm.calls) == 2


@pytest.mark.asyncio
async def test_requests_are_paced_for_the_read_bucket(session):
    await _snapshot(session)
    await _snapshot(session, org(OTHER_ID, name="Other"))
    await _linked_item(session)
    await _linked_item(session, OTHER_ID)
    pm = FakePowerMap(org(), org(OTHER_ID, name="Other"))
    sleeps = _Sleeps()

    await _refresh(session, pm, pace_seconds=0.5, sleep=sleeps)

    assert sleeps.calls == [0.5]


@pytest.mark.asyncio
async def test_a_retry_after_too_long_to_wait_ends_the_sweep(session):
    """CR 4: Power Map asked for a long pause; the next hour is the retry."""
    for pm_org_id in (WSLCB_ID, OTHER_ID, WINNER_ID):
        await _snapshot(session, org(pm_org_id, name=pm_org_id))
        await _linked_item(session, pm_org_id)
    pm = FakePowerMap()
    pm.unavailable = PowerMapUnavailableError("rate limited (HTTP 429)", retry_after=600)
    sleeps = _Sleeps()

    outcomes = await _refresh(session, pm, sleep=sleeps)

    assert list(outcomes.values()) == [UNAVAILABLE]
    assert len(pm.calls) == 1
    assert sleeps.calls == []


@pytest.mark.asyncio
async def test_a_long_retry_after_on_the_retry_still_ends_the_sweep(session):
    """CR 12: the retry goes through the same rule as the first attempt."""
    for pm_org_id in (WSLCB_ID, OTHER_ID, WINNER_ID):
        await _snapshot(session, org(pm_org_id, name=pm_org_id))
        await _linked_item(session, pm_org_id)
    pm = FakePowerMap(org(), org(OTHER_ID, name=OTHER_ID), org(WINNER_ID, name=WINNER_ID))
    pm.failures += [
        PowerMapUnavailableError("rate limited (HTTP 429)", retry_after=5),
        PowerMapUnavailableError("rate limited (HTTP 429)", retry_after=600),
    ]
    sleeps = _Sleeps()

    outcomes = await _refresh(session, pm, sleep=sleeps)

    assert list(outcomes.values()) == [UNAVAILABLE]
    assert len(pm.calls) == 2
    assert sleeps.calls == [5]


@pytest.mark.asyncio
async def test_the_order_is_shuffled_each_run(session, monkeypatch):
    """CR 1: a failure never advances ``checked_at``, so oldest-first would put
    the same failing orgs first every run and end every sweep before the rest."""
    for pm_org_id in (WSLCB_ID, OTHER_ID):
        await _snapshot(session, org(pm_org_id, name=pm_org_id))
        await _linked_item(session, pm_org_id)
    pm = FakePowerMap(org(), org(OTHER_ID, name=OTHER_ID))
    monkeypatch.setattr(follower, "_shuffle", lambda rows: rows.reverse())

    await _refresh(session, pm)

    assert [c[1] for c in pm.calls] == sorted([WSLCB_ID, OTHER_ID], reverse=True)


@pytest.mark.asyncio
async def test_the_sweep_stops_after_consecutive_failures(session):
    ids = [f"01JPM0000000000000000000{n:02d}" for n in range(5)]
    for pm_org_id in ids:
        await _snapshot(session, org(pm_org_id, name=pm_org_id))
        await _linked_item(session, pm_org_id)
    pm = FakePowerMap()
    pm.unavailable = PowerMapUnavailableError("request timed out")

    outcomes = await _refresh(session, pm)

    assert len(pm.calls) == follower.MAX_CONSECUTIVE_FAILURES
    assert list(outcomes.values()) == [UNAVAILABLE] * follower.MAX_CONSECUTIVE_FAILURES


@pytest.mark.asyncio
async def test_a_rename_waits_for_the_info_item_row_lock(test_engine, committed_rows):
    """#302: the follower's write serializes with assign, save and link."""
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with make_session() as setup:
        await _snapshot(setup)
        item = InfoItem(name="follower race item", rep_fields={}, pm_org_id=WSLCB_ID)
        setup.add(item)
        await setup.commit()
    committed_rows.extend([(PmOrganization, WSLCB_ID), (InfoItem, item.info_item_id)])
    pm = FakePowerMap(org(name="WA Cannabis Board", pm_updated_at=T1, etag='"v2"'))

    async with make_session() as holder, make_session() as sweeper:
        await lock_info_item(holder, item.info_item_id)
        task = asyncio.create_task(refresh_linked_orgs(sweeper, pm, pace_seconds=0))
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "the follower renamed while another writer held the InfoItem row"

        await holder.commit()
        assert await asyncio.wait_for(task, timeout=10.0) == {WSLCB_ID: RENAMED}


# ---------------------------------------------------------------------------
# End to end: the next occasion renders the new path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_occasion_issued_after_a_rename_renders_the_new_path(session):
    await _snapshot(session)
    item = await _linked_item(session, assigned=True)
    source = InfoSource(
        url="https://example.com/pm-follower",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(source)
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=source.info_source_id)
    )
    await session.flush()

    pm = FakePowerMap(org(name="WA Cannabis Board", pm_updated_at=T1, etag='"v2"'))
    assert await _refresh(session, pm) == {WSLCB_ID: RENAMED}
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "c" * 64,
        captured_at=T1,
        content_cache_uri="file:///var/lib/replicator/blobs/cc.bin",
        source_media_type="text/html",
    )
    session.add(revision)
    await session.flush()

    (command,) = await issue_for_revision(session, revision)

    assert command.destination.startswith("organizations/wa_cannabis_board/")


# ---------------------------------------------------------------------------
# The timer entrypoint
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_main_deps(monkeypatch):
    """Neutralise everything ``main`` touches outside the sweep (CR 2); hand back
    the spies its contracts are asserted on."""
    monkeypatch.setattr(follower, "configure_logging", lambda: None)
    monkeypatch.setattr(follower, "get_database_url", lambda: "postgresql://db/archiver")
    gate = MagicMock()
    monkeypatch.setattr(follower, "assert_production_db_allowed", gate)
    client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(follower, "power_map_from_env", lambda: client)
    session = object()

    @asynccontextmanager
    async def _session():
        yield session

    monkeypatch.setattr(follower, "get_session_factory", lambda: _session)
    engine = AsyncMock()
    monkeypatch.setattr(follower, "get_engine", MagicMock(return_value=engine))
    sweep = AsyncMock(return_value={})
    monkeypatch.setattr(follower, "refresh_linked_orgs", sweep)
    return SimpleNamespace(gate=gate, client=client, session=session, engine=engine, sweep=sweep)


def test_main_sweeps_then_releases_the_client_and_engine(stub_main_deps):
    assert main([]) == 0

    stub_main_deps.sweep.assert_awaited_once_with(stub_main_deps.session, stub_main_deps.client)
    stub_main_deps.client.aclose.assert_awaited_once()
    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_releases_both_when_the_sweep_crashes(stub_main_deps):
    stub_main_deps.sweep.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        main([])

    stub_main_deps.client.aclose.assert_awaited_once()
    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_gates_the_production_database_on_the_units_flag(stub_main_deps, monkeypatch):
    monkeypatch.setenv("ARCHIVER_ALLOW_PRODUCTION_DB", "1")

    main([])

    stub_main_deps.gate.assert_called_once_with("postgresql://db/archiver", allow_flag="1")


def test_main_is_dormant_without_a_key(stub_main_deps, monkeypatch):
    monkeypatch.setattr(follower, "power_map_from_env", lambda: None)

    def _no_database(*_args, **_kwargs):
        raise AssertionError("a dormant follower must not touch the database")

    monkeypatch.setattr(follower, "get_database_url", _no_database)
    monkeypatch.setattr(follower, "assert_production_db_allowed", _no_database)

    assert main([]) == 0
    stub_main_deps.sweep.assert_not_awaited()
