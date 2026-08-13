"""The lifespan's bus wiring — publisher and consumer start conditions.

`consumer_enabled` is unit-tested in isolation, but the gate it feeds is the
safety control (`AGENTS.md`, "Four variables carry safety rules"), and an
untested safety control is an assertion about behaviour rather than a guarantee
of it (CR round 1, finding 8).

Covers:
1. No `ARCHIVER_REDIS_URL` → neither publisher nor consumer
2. Redis but no gate → publisher runs, consumer does not
3. Redis + gate → both run
4. Gate set but Redis absent → still no consumer (the gate is not its own switch)
5. Both tasks stop on shutdown
6. A consumer that cannot start leaves the publisher running
7. The registry-snapshot task starts and stops with the publisher, and its
   task/trigger handles are nulled on the dormant path (archiver#141)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fakeredis import aioredis as fakeredis_aio

from src.api.main import app, lifespan

FAKE_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture
def fake_redis_from_url():
    """Make ``RedisAsync.from_url`` in the lifespan hand back a FakeRedis."""
    clients = []

    def _from_url(*_args, **_kwargs):
        client = fakeredis_aio.FakeRedis()
        clients.append(client)
        return client

    with patch("src.api.main.RedisAsync.from_url", side_effect=_from_url):
        yield clients


@pytest.fixture
def bus_env(monkeypatch):
    """Start from a known-clean bus environment for each case."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    monkeypatch.delenv("ARCHIVER_BUS_CONSUMER", raising=False)
    return monkeypatch


@pytest.mark.asyncio
async def test_no_redis_url_starts_neither(bus_env, test_engine):
    async with lifespan(app):
        assert app.state.redis_client is None
        assert app.state.revisions_consumer_task is None
        # Dormant nulls both snapshot handles too — the republish route's 409
        # hangs off registry_snapshot_trigger being None (CR round 3, #12).
        assert app.state.registry_snapshot_task is None
        assert app.state.registry_snapshot_trigger is None


@pytest.mark.asyncio
async def test_redis_without_the_gate_starts_publisher_only(
    bus_env, fake_redis_from_url, test_engine
):
    """Presence of a Redis URL is not authority to join a production group."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)

    async with lifespan(app):
        assert app.state.redis_client is not None
        assert app.state.publisher_task is not None
        assert app.state.revisions_consumer_task is None
        # The snapshot task rides the publisher's gate, not the consumer's.
        assert app.state.registry_snapshot_task is not None
        assert not app.state.registry_snapshot_task.done()
        assert app.state.registry_snapshot_trigger is not None


@pytest.mark.asyncio
async def test_gate_without_redis_starts_neither(bus_env, test_engine):
    """The gate is a second condition, not an alternative one."""
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.redis_client is None
        assert app.state.revisions_consumer_task is None


@pytest.mark.asyncio
async def test_redis_and_gate_start_both(bus_env, fake_redis_from_url, test_engine):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        assert app.state.publisher_task is not None
        assert app.state.revisions_consumer_task is not None
        assert not app.state.revisions_consumer_task.done()


@pytest.mark.asyncio
async def test_both_tasks_stop_on_shutdown(bus_env, fake_redis_from_url, test_engine):
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    async with lifespan(app):
        publisher_task = app.state.publisher_task
        consumer_task = app.state.revisions_consumer_task
        snapshot_task = app.state.registry_snapshot_task

    assert publisher_task.done()
    assert consumer_task.done()
    assert snapshot_task.done()


@pytest.mark.asyncio
async def test_consumer_failure_leaves_the_publisher_running(
    bus_env, fake_redis_from_url, test_engine
):
    """The two are gated and constructed separately for exactly this reason."""
    bus_env.setenv("ARCHIVER_REDIS_URL", FAKE_REDIS_URL)
    bus_env.setenv("ARCHIVER_BUS_CONSUMER", "1")

    with patch(
        "src.core.changes.consumer.build_consumer", side_effect=RuntimeError("no consumer for you")
    ):
        async with lifespan(app):
            assert app.state.publisher_task is not None
            assert not app.state.publisher_task.done()
            assert app.state.revisions_consumer_task is None
