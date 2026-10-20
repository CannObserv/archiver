"""The lifespan's liveness heartbeat (archiver#297): on, off, and what it watches.

``CO_ARCHIVER_LIVE_MONITOR_ID`` lives only in ``deploy/archiver.service``, and the
key only in its ``$CREDENTIALS_DIRECTORY``, so every other process is off. Status
is respx here, for every test: never the network, never the real monitor or key.

Covers:
1. No monitor id: off, no task, the service starts
2. A monitor without its key: off at ERROR, the service starts
3. On, with the bus and the consumer gate: one check-in naming all four loops
4. On, bus-dormant: the publisher is still expected, so silence
5. The heartbeat is cancelled first at shutdown
6. An unreadable REVISION still starts the service
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fakeredis import aioredis as fakeredis_aio

from src.api import main
from src.api.main import app, lifespan
from src.core import liveness
from src.core.status_checkin import CREDENTIAL_NAME

STATUS = "http://status.test:9000"
MONITOR = "01M46EXP45TVCVAMQXK043N1Q7"
KEY = "sk-test-0123456789abcdef"
CHECKIN = f"{STATUS}/api/v1/monitors/{MONITOR}/checkin"
#: ``Heartbeat._in_thread``'s thread name, which the ``status`` drain joins by.
CHECKIN_THREAD = "liveness-checkin"


@pytest.fixture
def fake_bus():
    """The lifespan's broker is a FakeRedis (see ``test_lifespan_bus_wiring``)."""
    with patch(
        "src.core.changes.bus_client.RedisAsync.from_url",
        side_effect=lambda *_a, **_k: fakeredis_aio.FakeRedis(),
    ):
        yield


@pytest.fixture(autouse=True)
def status(respx_mock):
    """Status, stubbed, with every check-in this test started finished inside the stub.

    Cancelling the heartbeat never stops a check-in thread, and a tick due at once
    can start one just before the cancel. ``httpx.post`` then builds its client for
    tens of ms before it sends, and unjoined, that post outlives ``respx_mock``. It
    lands on the next test's route, or on the network (archiver#406). This teardown
    runs before ``respx_mock``'s, so every post lands here. Each post's thread name
    is checked too: renamed, the drain would match nothing and pass silently. Only a
    post that reaches the stub is seen, so test 3's check-in is what trips it.
    """
    posters: set[str] = set()

    def answer(request: httpx.Request) -> httpx.Response:
        posters.add(threading.current_thread().name)
        return httpx.Response(202, json={})

    before = set(threading.enumerate())
    yield respx_mock.post(CHECKIN).mock(side_effect=answer)
    for thread in set(threading.enumerate()) - before:
        if thread.name == CHECKIN_THREAD:
            thread.join(liveness.TIMEOUT_SECONDS)
            assert not thread.is_alive(), "a check-in outlived its test's Status stub"
    assert posters <= {CHECKIN_THREAD}, f"undrained check-in threads: {posters}"


@pytest.fixture
def live_env(monkeypatch, tmp_path: Path):
    """A unit's view: the monitor id, the key as a credential, a stubbed Status."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    monkeypatch.delenv("ARCHIVER_BUS_CONSUMER", raising=False)
    (tmp_path / CREDENTIAL_NAME).write_text(f"{KEY}\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(liveness.MONITOR_ID_ENV, MONITOR)
    monkeypatch.setenv("ARCHIVER_STATUS_URL", STATUS)
    # The first tick waits one interval: 300 s in production, a moment here.
    monkeypatch.setattr(liveness, "INTERVAL_SECONDS", 0.1)
    return monkeypatch


def _messages(caplog) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "src.core.liveness"]


async def test_no_monitor_id_is_off(monkeypatch, test_engine, caplog):
    monkeypatch.delenv(liveness.MONITOR_ID_ENV, raising=False)
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        async with lifespan(app):
            assert app.state.liveness_task is None
    assert (logging.INFO, "liveness: off") in _messages(caplog)


async def test_a_monitor_without_its_key_is_off_and_the_service_runs(
    live_env, tmp_path, test_engine, caplog
):
    """The unit's ``SetCredential=`` fallback: a lone newline."""
    (tmp_path / CREDENTIAL_NAME).write_text("\n")
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        async with lifespan(app):
            assert app.state.liveness_task is None
    assert (
        logging.ERROR,
        "liveness: off: missing the status-checkin-key credential",
    ) in _messages(caplog)


async def test_on_checks_in_for_every_expected_loop(
    live_env, fake_bus, test_engine, status, caplog
):
    live_env.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/15")
    live_env.setenv("ARCHIVER_BUS_CONSUMER", "1")
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        async with lifespan(app):
            assert app.state.liveness_task is not None
            # The consumers' first blocking read is up to 5 s on the fake bus.
            async with asyncio.timeout(15):
                while not status.called:
                    await asyncio.sleep(0.01)
    assert (logging.INFO, f"liveness: on {MONITOR}") in _messages(caplog)
    body = json.loads(status.calls[0].request.content)
    assert body["status"] == "ok"
    assert set(body["variables"]) == {
        "build",
        "publisher_age_s",
        "watch_status_tail_age_s",
        "revisions_consumer_age_s",
        "artifacts_consumer_age_s",
        "backing_off",
    }


async def test_on_without_the_bus_is_silence(live_env, test_engine, status, caplog):
    """Only the unit sets the id, and production without a bus is broken."""
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        async with lifespan(app):
            async with asyncio.timeout(5):
                while not any(
                    m == "bus loops not progressing; not checking in" for _, m in _messages(caplog)
                ):
                    await asyncio.sleep(0.01)
    assert not status.called
    (record,) = [r for r in caplog.records if r.getMessage().startswith("bus loops not")]
    assert record.reasons == ["publisher: not started"]


async def test_the_heartbeat_is_cancelled_before_the_bus_stops(
    live_env, fake_bus, test_engine, monkeypatch
):
    """A check-in taken while the loops wind down would report a dying service."""
    live_env.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/15")
    seen: list[bool] = []
    async with lifespan(app):
        heartbeat = app.state.liveness_task
        stop_event = app.state.publisher_stop_event
        real_set = stop_event.set
        monkeypatch.setattr(stop_event, "set", lambda: (seen.append(heartbeat.done()), real_set()))
    assert seen == [True]
    assert heartbeat.cancelled()


async def test_an_unreadable_revision_never_stops_the_service(live_env, test_engine, monkeypatch):
    """Liveness must never cost a start: the build is informational."""

    def _unreadable():
        raise PermissionError("REVISION")

    monkeypatch.setattr(main, "build_id", _unreadable)
    async with lifespan(app):
        assert app.state.liveness_task is not None
