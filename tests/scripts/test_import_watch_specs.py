"""CLI wrapper around the one-time watch_spec import (archiver#150).

The mapping logic is tested in ``tests/core/test_watch_spec_import.py``; this
covers the operator-facing surface — the flag that decides whether production is
written to, and the report the operator reads before trusting the run.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import scripts.import_watch_specs as iws
from scripts.import_watch_specs import format_report, parse_args, run
from src.core.watch_spec_import import ImportAnomaly, ImportReport, MappingRow


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


def test_format_report_prints_the_mapping_table_in_a_dry_run():
    """ "Verified against the live WatchedItems" needs the per-item rows, not counts."""
    out = format_report(
        ImportReport(
            dry_run=True,
            imported=1,
            mapping=[
                MappingRow(
                    info_item_id="01ABC",
                    wi_id="01WI",
                    disposition="imported",
                    watch_spec={"schema_version": 1, "interval": "1d"},
                    watch_active=False,
                )
            ],
        )
    )
    assert "01ABC" in out
    assert "01WI" in out
    assert "1d" in out
    assert "imported" in out


@pytest.mark.asyncio
async def test_run_exits_0_on_a_clean_report():
    with (
        patch(
            "scripts.import_watch_specs.import_watch_specs",
            AsyncMock(return_value=ImportReport(unchanged=4)),
        ),
        patch(
            "scripts.import_watch_specs._build_watcher",
            AsyncMock(return_value=MagicMock(aclose=AsyncMock())),
        ),
        patch("scripts.import_watch_specs._session_scope"),
    ):
        assert await run(dry_run=False) == 0


# ---------------------------------------------------------------------------
# Post-cutover write guard (archiver#158)
# ---------------------------------------------------------------------------


def test_apply_is_refused_without_the_env_opt_in(monkeypatch, capsys):
    """The cutover made the dashboard a concurrent writer of both columns, and
    every write here is a blind overwrite. A stray ``--apply`` would clobber
    operator-authored policy *and announce the clobber* as desired state."""
    monkeypatch.delenv(iws.ALLOW_IMPORT_ENV, raising=False)

    assert iws.main(["--apply"]) == 2
    assert iws.ALLOW_IMPORT_ENV in capsys.readouterr().err


def test_dry_run_needs_no_opt_in(monkeypatch):
    """Reporting is always safe — the guard is on writing, not on looking."""
    monkeypatch.delenv(iws.ALLOW_IMPORT_ENV, raising=False)
    monkeypatch.delenv("WATCHER_BASE_URL", raising=False)

    # Exits 2 for the *missing Watcher config* reason, not the guard.
    assert iws.main([]) == 2


def test_apply_proceeds_with_the_env_opt_in(monkeypatch):
    monkeypatch.setenv(iws.ALLOW_IMPORT_ENV, "1")
    monkeypatch.delenv("WATCHER_BASE_URL", raising=False)

    # Past the guard, into the ordinary "no Watcher configured" exit.
    assert iws.main(["--apply"]) == 2
