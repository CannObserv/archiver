"""``src.core.liveness``: the service's heartbeat to ``co-archiver-live`` (archiver#297).

It checks in ``ok`` only while every expected bus loop is making progress, and
stays silent otherwise: Status's ``missing`` is the page. A check-in runs in a
daemon thread, bounded, one attempt per tick, so a slow or failing Status never
reaches a publish or an ack. Ported from CannObserv/processor's ``liveness.py``
(processor#39) and its tests; the gate is archiver's, since it watches several
loops where processor watches one.

Status is never reached: posts are fakes, respx, or a socket that never answers.
"""

import asyncio
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from functools import partial
from pathlib import Path

import httpx
import pytest
import respx

from src.core import liveness
from src.core.liveness import Gate, Heartbeat, LoopProgress
from src.core.status_checkin import CREDENTIAL_NAME, CheckinFailed, post_checkin

BASE = "http://status.test:9000"
MONITOR = "01M46EXP45TVCVAMQXK043N1Q7"
KEY = "sk-test-0123456789abcdef"
CHECKIN = f"{BASE}/api/v1/monitors/{MONITOR}/checkin"


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Task:
    """Stands in for an ``asyncio.Task``: the gate asks it only ``done()``."""

    def __init__(self, done: bool = False) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


@pytest.fixture
def clock() -> Clock:
    return Clock()


def gate_of(clock: Clock, **loops: LoopProgress) -> Gate:
    return Gate(
        loops={name: (Task(), progress) for name, progress in loops.items()},
        tasks={},
        stale_after_s=300.0,
        clock=clock,
    )


def beat(gate: Gate, post, **overrides) -> Heartbeat:
    knobs = {"interval_s": 300.0, "timeout_s": 15.0} | overrides
    return Heartbeat(gate, post, build="abc123def456", **knobs)


def records(caplog, message: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == message]


# --- LoopProgress ------------------------------------------------------------


def test_progress_starts_fresh_at_creation(clock):
    """A loop's first blocking read is not an outage: creation counts as progress."""
    progress = LoopProgress(clock)
    assert progress.last == clock.now
    assert progress.backing_off is False


def test_a_stamp_moves_progress_and_records_backoff(clock):
    progress = LoopProgress(clock)
    clock.now += 7
    progress.stamp(backing_off=True)
    assert (progress.last, progress.backing_off) == (clock.now, True)
    progress.stamp()
    assert progress.backing_off is False


# --- Gate ----------------------------------------------------------------------


def test_every_fresh_loop_reads_fresh_with_its_age(clock):
    publisher, tail = LoopProgress(clock), LoopProgress(clock)
    clock.now += 42.4
    tail.stamp(backing_off=True)
    reading = gate_of(clock, publisher=publisher, watch_status_tail=tail).read()
    assert reading.fresh
    assert reading.variables == {
        "publisher_age_s": "42",
        "watch_status_tail_age_s": "0",
        "backing_off": "watch_status_tail",
    }


def test_no_loop_backing_off_reads_none(clock):
    reading = gate_of(clock, publisher=LoopProgress(clock)).read()
    assert reading.variables["backing_off"] == "none"


def test_progress_at_the_bound_is_still_fresh(clock):
    publisher = LoopProgress(clock)
    clock.now += 300.0
    assert gate_of(clock, publisher=publisher).read().fresh


def test_one_stale_loop_is_silence(clock):
    publisher, consumer = LoopProgress(clock), LoopProgress(clock)
    clock.now += 300.5
    publisher.stamp()
    reading = gate_of(clock, publisher=publisher, revisions_consumer=consumer).read()
    assert not reading.fresh
    assert reading.reasons == ("revisions_consumer: stale 300 s",)


def test_an_expected_loop_that_never_started_is_silence(clock):
    """Init failed, so the lifespan holds ``None``: nothing is consuming."""
    gate = Gate(
        loops={"publisher": (None, LoopProgress(clock))},
        tasks={},
        stale_after_s=300.0,
        clock=clock,
    )
    reading = gate.read()
    assert not reading.fresh
    assert reading.reasons == ("publisher: not started",)


def test_an_exited_loop_is_silence_however_fresh_its_last_stamp(clock):
    gate = Gate(
        loops={"publisher": (Task(done=True), LoopProgress(clock))},
        tasks={},
        stale_after_s=300.0,
        clock=clock,
    )
    reading = gate.read()
    assert not reading.fresh
    assert reading.reasons == ("publisher: exited",)


@pytest.mark.parametrize(
    ("task", "reason"),
    [(None, "replication_reaper: not started"), (Task(done=True), "replication_reaper: exited")],
)
def test_a_periodic_task_is_checked_for_running_only(clock, task, reason):
    """The hourly snapshot and the 900 s reaper stamp nothing: alive is not done()."""
    gate = Gate(
        loops={"publisher": (Task(), LoopProgress(clock))},
        tasks={"replication_reaper": task},
        stale_after_s=300.0,
        clock=clock,
    )
    reading = gate.read()
    assert not reading.fresh
    assert reading.reasons == (reason,)
    assert "replication_reaper_age_s" not in reading.variables


def test_a_running_periodic_task_reads_fresh(clock):
    gate = Gate(
        loops={"publisher": (Task(), LoopProgress(clock))},
        tasks={"registry_snapshot": Task()},
        stale_after_s=300.0,
        clock=clock,
    )
    assert gate.read().fresh


# --- Heartbeat: one tick -------------------------------------------------------


async def test_a_fresh_gate_checks_in_ok_with_every_variable(clock):
    posts = []
    publisher = LoopProgress(clock)
    clock.now += 12
    await beat(gate_of(clock, publisher=publisher), lambda v: posts.append(v) or 202).tick()
    assert posts == [{"build": "abc123def456", "publisher_age_s": "12", "backing_off": "none"}]


@respx.mock
async def test_the_real_post_sends_ok_with_the_key_in_its_header_only(clock):
    route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
    post = partial(post_checkin, BASE, MONITOR, KEY, "ok")
    await beat(gate_of(clock, publisher=LoopProgress(clock)), post).tick()
    (call,) = route.calls
    assert call.request.headers["X-API-Key"] == KEY
    body = json.loads(call.request.content)
    assert body["status"] == "ok"
    assert body["variables"]["build"] == "abc123def456"
    assert KEY not in call.request.content.decode()


async def test_a_stale_gate_stays_silent_and_says_why(clock, caplog):
    posts = []
    publisher = LoopProgress(clock)
    clock.now += 301
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await beat(gate_of(clock, publisher=publisher), posts.append).tick()
    assert posts == []
    (record,) = records(caplog, "bus loops not progressing; not checking in")
    assert record.levelno == logging.WARNING
    assert record.reasons == ["publisher: stale 301 s"]


@pytest.mark.parametrize(("code", "detail"), [(500, "500"), (401, "401 bad key")])
@respx.mock
async def test_a_refusal_is_one_warning_and_the_next_tick_tries_again(clock, caplog, code, detail):
    route = respx.post(CHECKIN).mock(
        return_value=httpx.Response(code, json={"detail": "bad key"} if code == 401 else {})
    )
    heartbeat = beat(
        gate_of(clock, publisher=LoopProgress(clock)),
        partial(post_checkin, BASE, MONITOR, KEY, "ok"),
    )
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await heartbeat.tick()
        await heartbeat.tick()
    assert route.call_count == 2
    failed = records(caplog, "liveness check-in failed")
    assert [r.levelno for r in failed] == [logging.WARNING] * 2
    assert failed[0].error == detail
    assert KEY not in caplog.text


async def test_unreachable_status_is_a_warning(clock, caplog):
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{probe.getsockname()[1]}"
    post = partial(post_checkin, url, MONITOR, KEY, "ok")
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await beat(gate_of(clock, publisher=LoopProgress(clock)), post).tick()
    (record,) = records(caplog, "liveness check-in failed")
    assert record.error.startswith("ConnectError")


async def test_an_unexpected_error_is_a_warning_never_an_escape(clock, caplog):
    def post(variables):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await beat(gate_of(clock, publisher=LoopProgress(clock)), post).tick()
    (record,) = records(caplog, "liveness check-in failed")
    assert record.error == "RuntimeError: boom"


@pytest.fixture
def hung_status() -> Iterator[str]:
    """A Status that accepts the connection and never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                accepted.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}"
    finally:
        stop.set()
        thread.join(2)
        for conn in accepted:
            conn.close()
        server.close()


async def test_a_hung_status_is_cut_off_and_the_next_tick_is_skipped(hung_status, caplog):
    # httpx's own timeout is longer, so the heartbeat's bound is what cuts it off.
    gate = Gate(loops={"publisher": (Task(), LoopProgress())}, tasks={}, stale_after_s=300.0)
    post = partial(post_checkin, hung_status, MONITOR, KEY, "ok", timeout=5)
    heartbeat = beat(gate, post, timeout_s=0.2)
    started = time.monotonic()
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await heartbeat.tick()
        assert time.monotonic() - started < 1.0
        # The thread is still waiting on httpx's 5 s.
        await heartbeat.tick()
    (failed,) = records(caplog, "liveness check-in failed")
    assert failed.error == "timed out after 0.2 s"
    (skipped,) = records(caplog, "previous check-in still in flight; skipping this tick")
    assert skipped.levelno == logging.WARNING


async def test_a_hung_status_never_delays_the_event_loop(hung_status):
    """A publish or an ack is a coroutine on this loop: it must keep turning."""
    gate = Gate(loops={"publisher": (Task(), LoopProgress())}, tasks={}, stale_after_s=300.0)
    post = partial(post_checkin, hung_status, MONITOR, KEY, "ok", timeout=5)
    task = asyncio.create_task(beat(gate, post, timeout_s=3).tick())
    try:
        turns = 0
        started = time.monotonic()
        while time.monotonic() - started < 0.5:
            await asyncio.sleep(0.01)
            turns += 1
        assert turns > 20
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_cut_off_check_in_frees_the_next_tick_once_its_post_returns(clock, caplog):
    # processor#45 CR 1: a post cut off by the timeout keeps later ticks skipping
    # only until it returns. Were the marker cleared on the loop, where settle
    # drops a cut-off result, one hung Status would silence the heartbeat.
    release = threading.Event()
    threads = []

    def post(variables):
        threads.append(threading.current_thread())
        if len(threads) == 1:
            release.wait(5)
        return 202

    heartbeat = beat(gate_of(clock, publisher=LoopProgress(clock)), post, timeout_s=0.05)
    try:
        with caplog.at_level(logging.INFO, logger="src.core.liveness"):
            await heartbeat.tick()  # cut off: the post is still running
            await heartbeat.tick()  # skipped
            release.set()
            threads[0].join(5)
            await heartbeat.tick()
    finally:
        release.set()
    assert len(threads) == 2
    (failed,) = records(caplog, "liveness check-in failed")
    assert failed.error == "timed out after 0.05 s"
    assert len(records(caplog, "previous check-in still in flight; skipping this tick")) == 1
    (ok,) = records(caplog, "liveness check-in")
    assert ok.checkin == 202


async def test_a_finished_check_in_whose_thread_lingers_does_not_skip_the_next_tick(
    clock, caplog, monkeypatch
):
    # processor#45: the result reaches the loop before its thread exits.
    linger = threading.Event()

    class Lingering(threading.Thread):
        def run(self) -> None:
            super().run()
            if self.name == "liveness-checkin":
                linger.wait(5)

    monkeypatch.setattr(threading, "Thread", Lingering)
    posts = []
    heartbeat = beat(
        gate_of(clock, publisher=LoopProgress(clock)), lambda v: posts.append(v) or 202
    )
    try:
        with caplog.at_level(logging.INFO, logger="src.core.liveness"):
            await heartbeat.tick()
            await heartbeat.tick()
    finally:
        linger.set()
    assert len(posts) == 2
    assert records(caplog, "previous check-in still in flight; skipping this tick") == []


async def test_a_thread_that_fails_to_start_does_not_wedge_the_heartbeat(
    clock, caplog, monkeypatch
):
    # The in-flight marker is set before start(): a start that raises must clear
    # it, or every later tick would skip and the monitor would page for nothing.
    real_start = threading.Thread.start
    calls = 0

    def start(self) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", start)
    heartbeat = beat(gate_of(clock, publisher=LoopProgress(clock)), lambda v: 202)
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await heartbeat.tick()
        await heartbeat.tick()
    (failed,) = records(caplog, "liveness check-in failed")
    assert failed.error == "RuntimeError: can't start new thread"
    (ok,) = records(caplog, "liveness check-in")
    assert ok.checkin == 202


async def test_ok_is_logged_on_the_first_and_after_a_failure_only(clock, caplog):
    answers = [202, 202, 503, 202, 202]

    def post(variables):
        code = answers.pop(0)
        if code != 202:
            raise CheckinFailed(str(code))
        return code

    publisher = LoopProgress(clock)
    heartbeat = beat(gate_of(clock, publisher=publisher), post)
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        await heartbeat.tick()
        await heartbeat.tick()
        await heartbeat.tick()  # 503
        await heartbeat.tick()
        clock.now += 1000  # stale: silence
        await heartbeat.tick()
        publisher.stamp()
        await heartbeat.tick()
    ok = records(caplog, "liveness check-in")
    assert [r.levelno for r in ok] == [logging.INFO] * 3
    assert all(r.checkin == 202 for r in ok)


# --- Heartbeat: the run loop ---------------------------------------------------


async def test_run_ticks_at_once_then_every_interval():
    posts = []
    progress = LoopProgress()
    gate = Gate(loops={"publisher": (Task(), progress)}, tasks={}, stale_after_s=300.0)
    task = asyncio.create_task(beat(gate, posts.append, interval_s=0.1, timeout_s=0.05).run())
    try:
        async with asyncio.timeout(5):
            while len(posts) < 3:
                progress.stamp()
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancel_ends_run_promptly_mid_check_in(hung_status):
    gate = Gate(loops={"publisher": (Task(), LoopProgress())}, tasks={}, stale_after_s=300.0)
    post = partial(post_checkin, hung_status, MONITOR, KEY, "ok", timeout=30)
    task = asyncio.create_task(beat(gate, post, timeout_s=30).run())
    await asyncio.sleep(0.2)  # the first check-in is in flight, for up to 30 s
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 0.5


async def test_a_tick_that_raises_is_logged_and_the_heartbeat_lives_on(caplog):
    # processor CR 2: a bug outside tick's own handlers ended the task silently.
    reads = []

    class Broken:
        def read(self):
            reads.append(1)
            raise RuntimeError("bug")

    heartbeat = Heartbeat(Broken(), lambda v: 202, build="b", interval_s=0.05, timeout_s=0.04)
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        task = asyncio.create_task(heartbeat.run())
        try:
            async with asyncio.timeout(5):
                while len(reads) < 3:
                    assert not task.done(), task
                    await asyncio.sleep(0.01)
        finally:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    raised = records(caplog, "liveness tick raised")
    assert len(raised) >= 2 and raised[0].levelno == logging.ERROR
    assert raised[0].exc_info is not None


# --- poster_from_env: on / off / off-missing-key ---------------------------------


def _credentials(tmp_path: Path, content: str | None) -> dict[str, str]:
    if content is not None:
        (tmp_path / CREDENTIAL_NAME).write_text(content)
    return {"CREDENTIALS_DIRECTORY": str(tmp_path)}


def test_no_monitor_id_is_off(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        assert liveness.poster_from_env(_credentials(tmp_path, f"{KEY}\n")) is None
    (record,) = records(caplog, "liveness: off")
    assert record.levelno == logging.INFO


@pytest.mark.parametrize("content", [None, "\n"], ids=["absent", "fallback"])
def test_a_monitor_without_its_key_is_off_at_error(tmp_path, caplog, content):
    """The unit's ``SetCredential=`` fallback: the service runs, unmonitored, loudly."""
    env = _credentials(tmp_path, content) | {liveness.MONITOR_ID_ENV: MONITOR}
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        assert liveness.poster_from_env(env) is None
    (record,) = records(caplog, "liveness: off: missing the status-checkin-key credential")
    assert record.levelno == logging.ERROR


def test_no_credentials_directory_is_off_at_error(caplog):
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        assert liveness.poster_from_env({liveness.MONITOR_ID_ENV: MONITOR}) is None
    assert records(caplog, "liveness: off: missing the status-checkin-key credential")


@pytest.mark.parametrize(
    "plant",
    [
        lambda path: path.mkdir(),  # IsADirectoryError: an OSError, not FileNotFound
        lambda path: path.write_bytes(b"\xff\xfe\x00"),  # UnicodeDecodeError: a ValueError
    ],
    ids=["directory", "not-utf8"],
)
def test_an_unreadable_key_is_off_at_error_never_a_raise(tmp_path, caplog, plant):
    """A raise here would fail the lifespan, and deploy.sh would switch back."""
    plant(tmp_path / CREDENTIAL_NAME)
    env = {"CREDENTIALS_DIRECTORY": str(tmp_path), liveness.MONITOR_ID_ENV: MONITOR}
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        assert liveness.poster_from_env(env) is None
    assert records(caplog, "liveness: off: missing the status-checkin-key credential")


def test_a_malformed_monitor_id_is_off_at_error(tmp_path, caplog):
    env = _credentials(tmp_path, KEY) | {liveness.MONITOR_ID_ENV: "../../admin"}
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        assert liveness.poster_from_env(env) is None
    (record,) = records(caplog, f"liveness: off: {liveness.MONITOR_ID_ENV} is not a ULID")
    assert record.levelno == logging.ERROR


@respx.mock
def test_on_names_the_monitor_and_posts_ok_to_the_configured_status(tmp_path, caplog):
    route = respx.post(CHECKIN).mock(return_value=httpx.Response(202, json={}))
    env = _credentials(tmp_path, f"{KEY}\n") | {
        liveness.MONITOR_ID_ENV: MONITOR,
        "ARCHIVER_STATUS_URL": BASE,
    }
    with caplog.at_level(logging.INFO, logger="src.core.liveness"):
        post = liveness.poster_from_env(env)
    assert records(caplog, f"liveness: on {MONITOR}")
    assert KEY not in caplog.text
    assert post({"build": "b"}) == 202
    (call,) = route.calls
    assert json.loads(call.request.content) == {"status": "ok", "variables": {"build": "b"}}
