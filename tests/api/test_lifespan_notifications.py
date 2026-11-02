"""The lifespan's notification wiring (archiver#369): the consumer, the drain, the timer, T.

- The ``archiver.watch-events`` consumer runs under the same two gates as
  ``archiver.revisions``: a Redis URL **and** ``ARCHIVER_BUS_CONSUMER=1``.
- The reminder timer and retention run under ``ARCHIVER_BUS_CONSUMER`` alone,
  the replication reaper's rule: database-only, one sweeper.
- The drain runs only with a Notifier client.
- ``ARCHIVER_NOTIFY_CUTOVER_AT`` unset is shadow, and the journal says so. T
  without Notifier, or a T that isn't a UTC instant, refuses startup at CRITICAL.
- T and the text reader are bound for the consumer before it reads anything.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fakeredis import aioredis as fakeredis_aio

from src.api.main import app, lifespan
from src.core.changes import watch_events_consumer
from src.core.changes.watch_events_consumer import DispatchContext
from src.core.notifications.cutover import CUTOVER_ENV, CutoverRefused
from src.core.notifier.gate import API_KEY_ENV, BASE_URL_ENV, ENABLED_ENV

FAKE_REDIS_URL = "redis://localhost:6379/15"
T = "2026-11-20T17:00:00Z"
HANDLES = ("watch_events_consumer_task", "notification_drain_task", "notification_reminder_task")


@pytest.fixture
def fake_bus():
    with patch(
        "src.core.changes.bus_client.RedisAsync.from_url",
        side_effect=lambda *_a, **_k: fakeredis_aio.FakeRedis(),
    ):
        yield


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("ARCHIVER_REDIS_URL", "ARCHIVER_BUS_CONSUMER", CUTOVER_ENV):
        monkeypatch.delenv(name, raising=False)
    for handle in HANDLES:
        setattr(app.state, handle, "stale-from-a-previous-lifespan")
    yield monkeypatch
    watch_events_consumer.bind_context(DispatchContext())


def _dev_notifier(monkeypatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "http://notifier.test:9001")
    monkeypatch.setenv(API_KEY_ENV, "nk_test-0123456789abcdef")
    monkeypatch.setenv(ENABLED_ENV, "1")


async def test_dormant_starts_nothing_and_says_shadow(test_engine, caplog):
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            for handle in HANDLES:
                assert getattr(app.state, handle) is None
            assert watch_events_consumer.current_context() == DispatchContext()
    assert "notify cutover: unset (shadow)" in caplog.text


async def test_redis_and_gate_start_the_consumer_and_the_timer(
    clean_env, fake_bus, test_engine, caplog
):
    clean_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    clean_env.setenv("ARCHIVER_BUS_CONSUMER", "1")
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            consumer = app.state.watch_events_consumer_task
            timer = app.state.notification_reminder_task
            assert not consumer.done() and not timer.done()
            assert app.state.notification_drain_task is None
    assert consumer.done() and timer.done()
    assert "info.watch-events consumer task scheduled" in caplog.text


async def test_redis_without_the_gate_joins_no_group(clean_env, fake_bus, test_engine):
    clean_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    async with lifespan(app):
        assert app.state.watch_events_consumer_task is None
        assert app.state.notification_reminder_task is None


async def test_the_timer_runs_without_a_bus(clean_env, test_engine):
    """Database-only, like the reaper: reminders don't wait on the broker."""
    clean_env.setenv("ARCHIVER_BUS_CONSUMER", "1")
    async with lifespan(app):
        assert app.state.watch_events_consumer_task is None
        assert app.state.notification_reminder_task is not None


async def test_the_drain_runs_only_with_a_notifier(clean_env, test_engine, respx_mock):
    _dev_notifier(clean_env)
    async with lifespan(app):
        drain = app.state.notification_drain_task
        assert drain is not None and not drain.done()
    assert drain.done()
    assert not respx_mock.calls


async def test_t_is_bound_with_the_text_reader(clean_env, test_engine, respx_mock, caplog):
    _dev_notifier(clean_env)
    clean_env.setenv(CUTOVER_ENV, T)
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            context = watch_events_consumer.current_context()
            assert context.cutover == datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
            assert context.text_reader is app.state.text_reader
    assert "notify cutover: 2026-11-20T17:00:00.000000Z (facts at or after it send)" in caplog.text
    assert watch_events_consumer.current_context() == DispatchContext()


@pytest.mark.parametrize("raw", [T, "2026-11-20T17:00:00"])
async def test_a_t_that_cannot_send_refuses_startup_loudly(clean_env, test_engine, caplog, raw):
    """Without Notifier, or not a UTC instant: a misread T is a gap or a double send."""
    clean_env.setenv(CUTOVER_ENV, raw)
    with caplog.at_level(logging.CRITICAL, logger="src.api.main"), pytest.raises(CutoverRefused):
        async with lifespan(app):
            pytest.fail("the lifespan served with a refused cutover")
    (record,) = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert record.getMessage().startswith("Notify cutover: ")
