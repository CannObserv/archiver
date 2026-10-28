"""The daily temporal-profile boundary's timer entrypoint (archiver#365, D2).

The evaluation itself is ``tests/core/services/test_temporal_profiles.py``;
this pins what ``main`` adds: the UTC day, the ``--today`` override and its
refusal against production, the production gate, and engine release.
"""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.tools import temporal_boundary
from src.core.tools.temporal_boundary import main

PRODUCTION = "postgresql://db/archiver"
DEV = "postgresql://db/archiver_dev"
NOW = datetime(2026, 10, 27, 23, 59, 59, tzinfo=UTC)


@pytest.fixture
def stub_main_deps(monkeypatch):
    """Neutralise everything ``main`` touches outside the evaluation."""
    monkeypatch.setattr(temporal_boundary, "configure_logging", lambda: None)
    monkeypatch.setattr(temporal_boundary, "get_database_url", lambda: PRODUCTION)
    monkeypatch.setattr(temporal_boundary, "_now", lambda: NOW)
    gate = MagicMock()
    monkeypatch.setattr(temporal_boundary, "assert_production_db_allowed", gate)
    session = object()

    @asynccontextmanager
    async def _session():
        yield session

    monkeypatch.setattr(temporal_boundary, "get_session_factory", lambda: _session)
    engine = AsyncMock()
    monkeypatch.setattr(temporal_boundary, "get_engine", MagicMock(return_value=engine))
    run = AsyncMock(return_value={})
    monkeypatch.setattr(temporal_boundary, "run_boundary", run)
    return SimpleNamespace(gate=gate, session=session, engine=engine, run=run)


def test_the_logger_is_named_for_the_module_not_main():
    """A journald filter key: ``python -m`` would otherwise name it ``__main__``."""
    assert temporal_boundary.logger.name == "src.core.tools.temporal_boundary"


def test_main_evaluates_the_current_utc_day_and_releases_the_engine(stub_main_deps):
    assert main([]) == 0

    stub_main_deps.run.assert_awaited_once_with(stub_main_deps.session, today=date(2026, 10, 27))
    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_releases_the_engine_when_the_run_crashes(stub_main_deps):
    stub_main_deps.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        main([])

    stub_main_deps.engine.dispose.assert_awaited_once()


def test_main_gates_the_production_database_on_the_units_flag(stub_main_deps, monkeypatch):
    monkeypatch.setenv("ARCHIVER_ALLOW_PRODUCTION_DB", "1")

    main([])

    stub_main_deps.gate.assert_called_once_with(PRODUCTION, allow_flag="1")


def test_today_overrides_the_day_on_a_disposable_database(stub_main_deps, monkeypatch):
    """How 8001 steps a profile across dates (archiver_dev)."""
    monkeypatch.setattr(temporal_boundary, "get_database_url", lambda: DEV)

    assert main(["--today", "2027-01-15"]) == 0

    stub_main_deps.run.assert_awaited_once_with(stub_main_deps.session, today=date(2027, 1, 15))


@pytest.mark.parametrize("day", ["2026-10-26", "2026-10-28"])
def test_another_day_is_refused_against_production(stub_main_deps, day, caplog):
    """A past or future day on production would announce intervals early or late,
    and fire post-actions that are not due."""
    assert main(["--today", day]) == 2

    stub_main_deps.run.assert_not_awaited()
    assert "--today" in caplog.text


def test_todays_own_date_is_accepted_against_production(stub_main_deps):
    assert main(["--today", "2026-10-27"]) == 0

    stub_main_deps.run.assert_awaited_once()


def test_a_malformed_date_is_a_usage_error(stub_main_deps):
    with pytest.raises(SystemExit) as raised:
        main(["--today", "27/10/2026"])

    assert raised.value.code == 2
    stub_main_deps.run.assert_not_awaited()
