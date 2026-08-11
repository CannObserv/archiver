"""CLI wrapper around the one-time watch_spec import (archiver#150).

The mapping logic is tested in ``tests/core/test_watch_spec_import.py``; this
covers the operator-facing surface — the flag that decides whether production is
written to, and the report the operator reads before trusting the run.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.import_watch_specs import format_report, parse_args, run
from src.core.watch_spec_import import ImportAnomaly, ImportReport


def test_dry_run_is_the_default_so_a_bare_invocation_cannot_write():
    assert parse_args([]).dry_run is True


def test_apply_turns_writing_on():
    assert parse_args(["--apply"]).dry_run is False


def test_format_report_names_every_bucket():
    out = format_report(ImportReport(imported=3, unchanged=1, unlinked=2, failed=1))
    assert "imported" in out and "3" in out
    assert "unchanged" in out and "unlinked" in out and "failed" in out


def test_format_report_surfaces_anomalies_loudly():
    out = format_report(
        ImportReport(imported=1, anomalies=[ImportAnomaly("01ABC", "watcher_item_id mismatch")])
    )
    assert "ANOMALIES" in out.upper()
    assert "01ABC" in out
    assert "watcher_item_id mismatch" in out


def test_dry_run_label_is_visible_in_the_report():
    assert "DRY RUN" in format_report(ImportReport(dry_run=True, imported=1)).upper()


@pytest.mark.asyncio
async def test_run_reports_a_nonzero_exit_when_anomalies_are_present():
    """An operator running this in production must not read a clean exit as clean."""
    report = ImportReport(imported=1, anomalies=[ImportAnomaly("01ABC", "mismatch")])
    with (
        patch("scripts.import_watch_specs.import_watch_specs", AsyncMock(return_value=report)),
        patch(
            "scripts.import_watch_specs._build_watcher",
            AsyncMock(return_value=MagicMock(aclose=AsyncMock())),
        ),
        patch("scripts.import_watch_specs._session_scope"),
    ):
        assert await run(dry_run=True) == 1


@pytest.mark.asyncio
async def test_run_exits_2_when_watcher_is_not_configured():
    """No SDK credentials means there is nothing to import from — not a clean run."""
    with patch("scripts.import_watch_specs._build_watcher", AsyncMock(return_value=None)):
        assert await run(dry_run=True) == 2
