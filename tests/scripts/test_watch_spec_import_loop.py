"""One-time import of Watcher's cadence + active state onto InfoItem.watch_spec.

The SDK is the only reader of those two fields and archiver#142 deletes it, so
this import is the step's single irreversible action. It is written to be
re-runnable: it lands with archiver#150 and is run again immediately before the
announcement producer's first publish, because Watcher stays authoritative in
between.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from watcher_client import WatchedItemResponse

from scripts.import_watch_specs import import_watch_specs
from src.core.models import InfoItem

_TS = "2026-08-10T00:00:00+00:00"


def _wi(
    *,
    wi_id: str = "01HZZWATCHER00000000000001",
    is_active: bool = True,
    schedule_config: dict | None = None,
) -> WatchedItemResponse:
    return WatchedItemResponse.from_dict(
        {
            "id": wi_id,
            "name": "Test",
            "description": None,
            "is_active": is_active,
            "archived_at": None,
            "last_reviewed_at": None,
            "last_checked_at": None,
            "last_changed_at": None,
            "health_status": "unknown",
            "default_schedule_config": schedule_config,
            "content_media_type": None,
            "media_type_essence": None,
            "default_tags": None,
            "effective_url": "https://example.com/",
            "source_specs": [],
            "created_at": _TS,
            "updated_at": _TS,
        }
    )


def _watcher(**by_info_item_id: WatchedItemResponse | None) -> MagicMock:
    """A Watcher whose lookups are keyed by Archiver InfoItem ID.

    Keyed that way on purpose: the import joins from Watcher's
    ``archiver_info_item_id``, not from Archiver's drift-prone
    ``watcher_item_id``.
    """
    watcher = MagicMock()
    watcher.get_by_info_item_id = AsyncMock(
        side_effect=lambda item_id: by_info_item_id.get(item_id)
    )
    return watcher


async def _item(session, **kwargs) -> InfoItem:
    item = InfoItem(name=kwargs.pop("name", "Item"), **kwargs)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@pytest.mark.asyncio
async def test_imports_cadence_and_active_state(session):
    item = await _item(session, watcher_item_id="01HZZWATCHER00000000000001")
    watcher = _watcher(
        **{str(item.info_item_id): _wi(is_active=False, schedule_config={"interval": "6h"})}
    )

    report = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "interval": "6h"}
    assert item.watch_active is False
    assert report.imported == 1


@pytest.mark.asyncio
async def test_absent_schedule_config_imports_without_an_interval(session):
    """Watcher holding no per-item cadence is a real state, not a missing value.

    Fabricating one here would override Watcher's per-domain default.
    """
    item = await _item(session)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config=None)})

    await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1}
    assert item.watch_active is True


@pytest.mark.asyncio
async def test_joins_on_watcher_side_link_not_archivers_watcher_item_id(session):
    """A stale or absent watcher_item_id must not lose the row."""
    item = await _item(session, watcher_item_id=None)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config={"interval": "1h"})})

    report = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec["interval"] == "1h"
    assert report.imported == 1


@pytest.mark.asyncio
async def test_reports_a_watcher_item_id_mismatch_as_an_anomaly(session):
    item = await _item(session, watcher_item_id="01HZZSTALE0000000000000000")
    watcher = _watcher(
        **{
            str(item.info_item_id): _wi(
                wi_id="01HZZWATCHER00000000000001", schedule_config={"interval": "1h"}
            )
        }
    )

    report = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec["interval"] == "1h"  # Watcher's link wins; the row still imports
    assert report.imported == 1
    assert any("watcher_item_id" in a.reason for a in report.anomalies)


@pytest.mark.asyncio
async def test_item_with_no_watched_item_is_skipped_not_defaulted(session):
    item = await _item(session)
    watcher = _watcher()

    report = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1}
    assert item.watch_active is None  # untouched: no opinion imported
    assert report.imported == 0
    assert report.unlinked == 1


@pytest.mark.asyncio
async def test_unparseable_interval_is_an_anomaly_and_leaves_the_row_untouched(session):
    item = await _item(session)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config={"interval": "weekly"})})

    report = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1}
    assert item.watch_active is None  # a partial policy is worse than none
    assert report.imported == 0
    assert report.failed == 1
    assert any("weekly" in a.reason for a in report.anomalies)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_but_reports_what_it_would_do(session):
    item = await _item(session)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config={"interval": "7d"})})

    report = await import_watch_specs(session, watcher, dry_run=True)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1}
    assert item.watch_active is None
    assert report.imported == 1
    assert report.dry_run is True


@pytest.mark.asyncio
async def test_rerunning_is_idempotent_and_reports_no_further_changes(session):
    item = await _item(session)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config={"interval": "1d"})})

    first = await import_watch_specs(session, watcher)
    second = await import_watch_specs(session, watcher)

    await session.refresh(item)
    assert item.watch_spec == {"schema_version": 1, "interval": "1d"}
    assert item.watch_active is True
    assert first.imported == 1
    assert second.imported == 0
    assert second.unchanged == 1


@pytest.mark.asyncio
async def test_a_failing_lookup_skips_one_row_without_ending_the_pass(session):
    """Per-item isolation: the pass commits as it goes.

    Before this, the single commit at the end meant one transient Watcher error
    discarded every row already imported.
    """
    good = await _item(session, name="good")
    bad = await _item(session, name="bad")
    ok_wi = _wi(schedule_config={"interval": "6h"})

    watcher = MagicMock()

    async def _lookup(item_id):
        if item_id == str(bad.info_item_id):
            raise RuntimeError("watcher 503")
        return ok_wi

    watcher.get_by_info_item_id = AsyncMock(side_effect=_lookup)

    report = await import_watch_specs(session, watcher)

    await session.refresh(good)
    await session.refresh(bad)
    assert good.watch_spec == {"schema_version": 1, "interval": "6h"}
    assert bad.watch_spec == {"schema_version": 1}
    assert report.imported == 1
    assert report.failed == 1
    assert any("watcher 503" in a.reason for a in report.anomalies)


@pytest.mark.asyncio
async def test_a_failing_commit_skips_one_row_without_ending_the_pass(session, monkeypatch):
    """The other half of per-row isolation: the write can fail too.

    A deadlock or dropped connection on one row must not abandon the report and
    the rows behind it.
    """
    first = await _item(session, name="first")
    second = await _item(session, name="second")
    watcher = _watcher(
        **{
            str(first.info_item_id): _wi(schedule_config={"interval": "1h"}),
            str(second.info_item_id): _wi(schedule_config={"interval": "6h"}),
        }
    )

    real_commit = session.commit
    calls = {"n": 0}

    async def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("deadlock detected")
        return await real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    report = await import_watch_specs(session, watcher)

    assert report.failed == 1
    assert report.imported == 1
    assert any("deadlock detected" in a.reason for a in report.anomalies)

    # The failed row keeps its plan: on a failed run that is the only thing
    # telling the operator what the retry will do.
    failed_row = next(r for r in report.mapping if r.disposition == "failed")
    assert failed_row.watch_spec is not None
    assert failed_row.watch_active is True


@pytest.mark.asyncio
async def test_an_unlinked_item_is_an_anomaly_so_the_run_fails_loudly(session):
    """ "Assert 4/4 linked" — an item Watcher does not know about is a finding,
    not a quietly-skipped row."""
    await _item(session)
    watcher = _watcher()

    report = await import_watch_specs(session, watcher)

    assert report.unlinked == 1
    assert any("no WatchedItem" in a.reason for a in report.anomalies)


@pytest.mark.asyncio
async def test_the_report_carries_a_row_per_item_for_the_dry_run_table(session):
    item = await _item(session)
    watcher = _watcher(**{str(item.info_item_id): _wi(schedule_config={"interval": "7d"})})

    report = await import_watch_specs(session, watcher, dry_run=True)

    row = next(r for r in report.mapping if r.info_item_id == str(item.info_item_id))
    assert row.disposition == "imported"
    assert row.watch_spec == {"schema_version": 1, "interval": "7d"}
    assert row.watch_active is True
    assert row.wi_id == "01HZZWATCHER00000000000001"
