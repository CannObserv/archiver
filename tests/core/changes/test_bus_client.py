"""The long-lived bus client's connection policy (archiver#193 Phase 1).

Loopback masked the absence of one completely. Across the tailnet hop to the
relocated broker (CannObserv/broker#1) a stalled read has no bound, and a wedged
consumer coroutine sits inside a process whose ``/health`` stays green - it is
unauthenticated and DB-free by contract, so it cannot report a bus stall.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import subprocess
import sys

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

import src.core.changes as changes_pkg
from src.core.changes import bus_client, read_windows

# The most an unreachable broker may cost before the "run it detached" call in
# src/api/main.py stops being a preference and becomes the only option.
#
# Independent of ``SOCKET_TIMEOUT_SECONDS``, which it happens to equal today
# (CR round 3, finding 21). That one is derived from the blocking-read window;
# this one is a judgement about how long a lifespan may block. Nothing should
# move them together.
_INLINE_PROBE_CEILING_SECONDS = 10.0


def _blocking_read_windows_ms() -> dict[str, int]:
    """Every ``READ_BLOCK_MS`` defined anywhere under ``src.core.changes``.

    Discovered rather than listed. The invariant below is only as good as its
    knowledge of the loops, and a new consumer module is exactly the change that
    would otherwise slip past it - silently, since the symptom is a spurious
    timeout on an idle read rather than a failure anyone would attribute here.
    """
    found: dict[str, int] = {}
    for info in pkgutil.iter_modules(changes_pkg.__path__):
        module = importlib.import_module(f"{changes_pkg.__name__}.{info.name}")
        window = getattr(module, "READ_BLOCK_MS", None)
        if window is not None:
            found[info.name] = window
    return found


def test_discovery_finds_the_known_blocking_loops() -> None:
    """Guard the guard: a discovery helper that finds nothing passes vacuously."""
    windows = _blocking_read_windows_ms()
    assert {"group_consumer", "watch_status_consumer"} <= set(windows)
    assert all(w > 0 for w in windows.values())


def test_socket_timeout_exceeds_every_blocking_read_window() -> None:
    """``socket_timeout`` must clear the longest ``BLOCK``, with margin.

    Measured, not assumed: redis-py does **not** extend ``socket_timeout`` for a
    blocking command. A client built with ``socket_timeout=1`` raises
    ``TimeoutError`` after 1.01 s on an ``XREAD ... BLOCK 3000``; at
    ``socket_timeout=10`` the same call returns normally after 3.08 s.

    So a ``socket_timeout`` at or below ``READ_BLOCK_MS`` does not bound a stall,
    it manufactures one on every idle read - three loops spinning on spurious
    timeouts while the broker is perfectly healthy. This is the constraint behind
    the epic's "the values have to suit the slowest of them".
    """
    longest_s = max(_blocking_read_windows_ms().values()) / 1000
    assert bus_client.SOCKET_TIMEOUT_SECONDS > longest_s, (
        f"socket_timeout {bus_client.SOCKET_TIMEOUT_SECONDS}s does not clear the "
        f"longest blocking read window ({longest_s}s); idle reads would time out"
    )
    assert bus_client.SOCKET_TIMEOUT_SECONDS >= longest_s + bus_client.BLOCKING_READ_MARGIN_SECONDS


def test_socket_timeout_is_derived_not_transcribed() -> None:
    """Raising a loop's ``BLOCK`` must move the timeout with it.

    The same reasoning as ``group_name()`` in archiver#194: a coupling that lives
    only in a comment beside a literal is one someone edits half of.
    """
    assert bus_client.SOCKET_TIMEOUT_SECONDS == (
        read_windows.LONGEST_READ_BLOCK_MS / 1000 + bus_client.BLOCKING_READ_MARGIN_SECONDS
    )


def test_read_windows_is_actually_a_leaf() -> None:
    """The leaf must import nothing else from this package (CR round 3, finding 20).

    That property is the entire reason ``read_windows`` exists: ``bus_client``
    derives its timeout from it *instead of* importing the consumer modules,
    which had put client construction downstream of the loops that consume its
    client (round 2, finding 13). Until now the property was a docstring. Adding
    one ``from src.core.changes import group_consumer`` here would restore the
    cycle risk silently, and the symptom would arrive much later as an
    ``ImportError`` at startup - precisely the diagnosis the split was meant to
    spare someone.

    Imports it in a clean module table so the assertion is about what
    ``read_windows`` pulls in, not about what some earlier test already loaded.
    """
    code = (
        "import sys\n"
        "for m in [m for m in sys.modules if m.startswith('src.core.changes')]:\n"
        "    del sys.modules[m]\n"
        "from src.core.changes import read_windows\n"
        "pulled = sorted(m for m in sys.modules if m.startswith('src.core.changes'))\n"
        "print(repr(pulled))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    pulled = ast.literal_eval(result.stdout.strip())
    assert pulled == ["src.core.changes", "src.core.changes.read_windows"], (
        f"read_windows is no longer a leaf - it pulled in {pulled}"
    )


def test_the_leaf_actually_holds_the_longest_window() -> None:
    """``read_windows`` claims to know the longest window; check it against reality.

    Its name is the whole load-bearing part - ``bus_client`` trusts it instead of
    surveying the loops itself (CR round 2, finding 13). A leaf that is *wrong*
    about being the longest is worse than the import it replaced, because the
    error is silent and reads as authoritative. So the discovery walk that finds
    every real ``READ_BLOCK_MS`` is what audits it.
    """
    assert read_windows.LONGEST_READ_BLOCK_MS == max(_blocking_read_windows_ms().values())


def test_connect_timeout_is_bounded_and_shorter_than_the_read_timeout() -> None:
    """A refusing or black-holed broker must fail fast; a *slow* one must not.

    Connecting carries no ``BLOCK``, so it needs no headroom - and the tailnet
    path to the broker is a ~40 ms DERP relay, which a multi-second budget clears
    by two orders of magnitude.
    """
    assert 0 < bus_client.SOCKET_CONNECT_TIMEOUT_SECONDS < bus_client.SOCKET_TIMEOUT_SECONDS


def test_build_client_applies_the_whole_policy() -> None:
    client = bus_client.build_bus_client("redis://localhost:6379/14")
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == bus_client.SOCKET_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == bus_client.SOCKET_CONNECT_TIMEOUT_SECONDS
    assert kwargs["health_check_interval"] == bus_client.HEALTH_CHECK_INTERVAL_SECONDS


def test_client_takes_no_retry_because_a_retry_re_sends_the_command() -> None:
    """Zero retries, and the zero is the load-bearing part (CR finding 3).

    A redis-py retry **re-sends the command**; it does not resume a response.
    Confirmed in redis-py 7.4.1's source: ``Redis.execute_command`` wraps
    ``_send_command_parse_response`` in ``Retry.call_with_retry``. So a
    ``TimeoutError`` raised after the broker already applied an ``XADD``
    publishes the entry twice - a duplicate the outbox cannot see, because
    ``publish_attempts`` counts drain-loop attempts and not command-level ones.

    An earlier draft of this module set one retry. Nothing is lost by declining
    it: the loops retry with their own escalating backoff, the outbox is the
    durable buffer, and ``health_check_interval`` covers the stale-pooled-
    connection case a retry was reaching for.
    """
    client = bus_client.build_bus_client("redis://localhost:6379/14")
    assert bus_client.BUS_RETRIES == 0
    # Private attribute: redis-py publishes no accessor for the retry count.
    # tests/api/test_lifespan_bus_wiring.py reads the same one (CR round 2,
    # finding 15).
    assert client.connection_pool.make_connection().retry._retries == 0


def test_the_retryable_set_is_left_at_the_library_default() -> None:
    """``retry_on_error`` is deliberately not passed (CR finding 4).

    redis-py's ``Retry`` already carries exactly ``(ConnectionError,
    TimeoutError)``. Passing the same pair implied this widened something it did
    not. Asserted rather than merely deleted, so that if the library ever narrows
    its default the omission stops being safe and this says so.
    """
    client = bus_client.build_bus_client("redis://localhost:6379/14")
    supported = set(client.connection_pool.make_connection().retry._supported_errors)
    assert RedisConnectionError in supported
    assert RedisTimeoutError in supported


@pytest.mark.parametrize("url", ["", None])
def test_build_client_refuses_an_empty_url(url: str | None) -> None:
    """Dormancy is the caller's decision, not a client that quietly points at
    ``localhost``. ``ARCHIVER_REDIS_URL`` unset means bus-dormant; a client built
    from it anyway would connect to whatever answers on the default host."""
    with pytest.raises(ValueError):
        bus_client.build_bus_client(url)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Startup reachability - archiver#193 Phase 1 item 3, "a partition must be loud"
# ---------------------------------------------------------------------------


def test_worst_case_connect_is_bounded_by_retries_times_the_connect_timeout() -> None:
    """``socket_connect_timeout`` bounds one *attempt*, not the call.

    Measured against a black-holed address on redis-py 7.4.1: ``connect=5,
    retries=0`` raised at 5.01 s; ``connect=5, retries=1`` at 10.03 s;
    ``connect=2, retries=1`` at 4.02 s. So the budget an operator actually waits
    is ``(retries + 1) x socket_connect_timeout``, and reading the connect
    timeout alone understates it by the retry factor.

    Pinned because it is the number that decides whether the startup probe can
    run inline in the lifespan. It cannot - see ``probe_bus_reachable``.

    Asserts the **bound**, not the product (CR round 2, finding 12). An earlier
    version restated ``(BUS_RETRIES + 1) * SOCKET_CONNECT_TIMEOUT_SECONDS``,
    which is the line that defines the constant: an arithmetic identity that
    holds whatever redis-py does, so it could only fail if someone edited one
    half of a single expression. What actually matters is that the budget stays
    small enough that running the probe inline would still be a *choice* rather
    than a hang - raise either input past this ceiling and the detached-task
    reasoning in ``src/api/main.py`` needs revisiting, which is exactly when a
    test should speak up.
    """
    assert bus_client.WORST_CASE_CONNECT_SECONDS <= _INLINE_PROBE_CEILING_SECONDS


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("redis://localhost:6379/0", "redis://localhost:6379/0"),
        ("redis://:hunter2@broker:6379/0", "redis://:***@broker:6379/0"),
        ("redis://archiver:hunter2@broker:6379/0", "redis://archiver:***@broker:6379/0"),
        ("rediss://archiver:hunter2@broker:6380/0", "rediss://archiver:***@broker:6380/0"),
        ("redis://archiver@broker:6379/0", "redis://archiver@broker:6379/0"),
        # IPv6: urlsplit().hostname strips the brackets, so a naive rebuild
        # emits something that is no longer a URL (CR finding 5).
        ("redis://:hunter2@[::1]:6379/0", "redis://:***@[::1]:6379/0"),
        ("redis://user:hunter2@[2001:db8::1]:6379/0", "redis://user:***@[2001:db8::1]:6379/0"),
        # No password: returned verbatim, so the host keeps its original case.
        ("redis://BROKER.Example:6379/0", "redis://BROKER.Example:6379/0"),
    ],
)
def test_redact_url_removes_the_password(url: str, expected: str) -> None:
    """The broker gains a credential at CannObserv/broker#1 D3, and every log
    line naming the URL goes to journald. A probe that reports "unreachable" by
    printing the URL would publish the password to the one place an operator is
    guaranteed to look."""
    assert bus_client.redact_url(url) == expected


def test_redact_url_never_leaks_on_a_url_it_cannot_parse() -> None:
    """Fail closed. A redactor that re-raises or passes the input through on a
    malformed URL leaks exactly when something is already wrong."""
    redacted = bus_client.redact_url("redis://[not-a-valid-url:hunter2@@@")
    assert "hunter2" not in redacted


@pytest.mark.asyncio
async def test_probe_logs_error_when_the_broker_is_unreachable(monkeypatch) -> None:
    """An unreachable-but-configured broker must not present as an idle system.

    This is the gap the epic names and the reason the probe exists at all:
    ``from_url`` is **lazy** (verified - it returns in 0.000 s against a dead
    broker and raises nothing), so the lifespan's ``except Exception`` around
    publisher init cannot catch an unreachable broker. Startup succeeds, the
    publisher task is scheduled, and the first failure happens later inside a
    loop that correctly classifies it as transient and backs off quietly.
    """
    records: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        bus_client.logger,
        "error",
        lambda msg, *a, **k: records.append((msg, k.get("extra", {}))),
    )

    class _Dead:
        async def ping(self):
            raise RedisConnectionError("Error 111 connecting to broker:6379.")

    ok = await bus_client.probe_bus_reachable(_Dead(), "redis://:hunter2@broker:6379/0")

    assert ok is False
    assert len(records) == 1
    _msg, extra = records[0]
    assert extra["redis_url"] == "redis://:***@broker:6379/0"
    assert "hunter2" not in repr(records)


@pytest.mark.asyncio
async def test_probe_logs_info_with_latency_when_reachable(monkeypatch) -> None:
    """The success line carries the round trip, because the relocated broker is
    across a ~40 ms relay and "reachable" alone stops being the whole story."""
    records: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        bus_client.logger,
        "info",
        lambda msg, *a, **k: records.append((msg, k.get("extra", {}))),
    )

    class _Live:
        async def ping(self):
            return True

    ok = await bus_client.probe_bus_reachable(_Live(), "redis://broker:6379/0")

    assert ok is True
    assert len(records) == 1
    assert records[0][1]["rtt_ms"] >= 0


@pytest.mark.asyncio
async def test_probe_never_raises(monkeypatch) -> None:
    """It runs detached from the lifespan; an exception there would surface as a
    bare 'Task exception was never retrieved' and take the diagnosis backwards.

    ``BaseException`` is deliberately *not* caught - a CancelledError at shutdown
    must propagate, or the task would refuse to stop."""
    monkeypatch.setattr(bus_client.logger, "error", lambda *a, **k: None)

    class _Weird:
        async def ping(self):
            raise RuntimeError("something no one anticipated")

    assert await bus_client.probe_bus_reachable(_Weird(), "redis://broker:6379/0") is False
