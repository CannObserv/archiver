"""The liveness heartbeat: ``archiver.service`` checks in to ``co-archiver-live`` (archiver#297).

A task beside the bus loops, on the same event loop. Every ``interval_s`` it
checks in ``ok``, **only while every expected bus loop is making progress**: each
continuous loop (the outbox publisher, the two group consumers, the
``info.watch-status`` tail) stamped a :class:`LoopProgress` no more than
``stale_after_s`` ago and has not exited, and each periodic task (the registry
snapshot, the replication reaper) is still running. Anything else gets silence,
never an ``alert``. Status goes ``missing`` past the monitor's grace, and that is
the page. So a dead process, a crash loop that ends ``failed`` (the unit's
``StartLimitBurst=``), a wedged event loop, and a stalled or exited bus loop all
page the same way. An idle stream still turns its loop, so quiet is not an outage.

**What a loop stamps** (the operator decision on archiver#297): a broker outage
counts as alive, since broker has its own monitoring. A database outage does
not, since ``/health`` is DB-free and would otherwise never page. The loops
already split the two. The publisher stamps after each publish attempt and when
a drain returns, never before its SELECT answers: a publish error is caught per
row, so only the database reaches its backoff. The consumers and the tail stamp
every iteration, backoff included. A loop stamps nothing at creation, and the
first tick waits one interval: a start is not proof of life.

**Never in a publish's or an ack's way** (processor#39 trap 1):
:func:`~src.core.status_checkin.post_checkin` is blocking ``httpx``, so each
check-in runs in a daemon thread, awaited for at most ``timeout_s``:

- not ``asyncio.to_thread``: the default executor is shared with the extraction
  tool, and uvicorn's ``asyncio.run`` joins it at shutdown;
- a check-in still running at the next tick skips that tick, so threads never
  pile up. "Running" means its ``post`` has not returned, not that its thread is
  alive: the thread hands back its result a moment before it exits (processor#45);
- one attempt per tick, never a retry loop;
- a failure is one WARNING record, and the monitor's grace absorbs a missed tick.

Nothing here raises into the lifespan. Ported from CannObserv/processor's
``liveness.py``; the multi-loop :class:`Gate` is archiver's.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from src.core.logging import get_logger
from src.core.status_checkin import (
    CREDENTIAL_NAME,
    DEFAULT_STATUS_URL,
    MONITOR_ID_PATTERN,
    STATUS_URL_ENV,
    CheckinFailed,
    post_checkin,
    read_key,
)

logger = get_logger(__name__)

#: Set only by ``deploy/archiver.service``, never in an env file: a hand-run
#: server that sourced it would check in for production.
MONITOR_ID_ENV = "CO_ARCHIVER_LIVE_MONITOR_ID"
#: The monitor's interval (CannObserv/status#47).
INTERVAL_SECONDS = 300.0
#: A loop silent for longer is stalled. Every loop stamps far more often: the
#: consumers' blocking read is 5 s, the publisher's idle sleep 1 s, the longest
#: backoff 30 s, a broker socket timeout 10 s (the publisher stamps per row).
#: Under the interval, so a loop that dies just after a tick fails the next one.
STALE_AFTER_SECONDS = 120.0
#: The heartbeat's own bound on one check-in; httpx's 10 s normally fires first.
TIMEOUT_SECONDS = 15.0


class LoopProgress:
    """One continuous bus loop's last finished iteration.

    ``None`` until the first: creation is not progress. A process that dies
    before its loops turn must never check in, or a crash loop slower than
    ``StartLimitBurst=`` would report ``ok`` on every start (archiver#297 review).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.last: float | None = None
        self.backing_off = False

    def stamp(self, *, backing_off: bool = False) -> None:
        """Record a finished iteration, and whether it was a backoff."""
        self.last = self._clock()
        self.backing_off = backing_off


class _Task(Protocol):
    def done(self) -> bool: ...


@dataclass(frozen=True)
class Reading:
    """The gate's verdict: whether to check in, what to say, or why not."""

    fresh: bool
    variables: dict[str, str]
    reasons: tuple[str, ...]


class Gate:
    """Whether every expected bus loop is making progress.

    ``loops`` maps each expected continuous loop to its task and its progress;
    ``tasks`` each expected periodic task, alive while not ``done()``. A ``None``
    task is one whose init failed, which is silence like an exited one.
    """

    def __init__(
        self,
        *,
        loops: Mapping[str, tuple[_Task | None, LoopProgress]],
        tasks: Mapping[str, _Task | None],
        stale_after_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loops = loops
        self._tasks = tasks
        self._stale_after_s = STALE_AFTER_SECONDS if stale_after_s is None else stale_after_s
        self._clock = clock

    def read(self) -> Reading:
        """Read every expected loop and task once."""
        reasons: list[str] = []
        variables: dict[str, str] = {}
        backing_off: list[str] = []
        for name, (task, progress) in self._loops.items():
            if not _running(name, task, reasons):
                continue
            if progress.last is None:
                reasons.append(f"{name}: no progress yet")
                continue
            age = self._clock() - progress.last
            variables[f"{name}_age_s"] = str(round(age))
            if age > self._stale_after_s:
                reasons.append(f"{name}: stale {round(age)} s")
            if progress.backing_off:
                backing_off.append(name)
        for name, task in self._tasks.items():
            _running(name, task, reasons)
        variables["backing_off"] = ",".join(backing_off) or "none"
        return Reading(fresh=not reasons, variables=variables, reasons=tuple(reasons))


def _running(name: str, task: _Task | None, reasons: list[str]) -> bool:
    if task is None:
        reasons.append(f"{name}: not started")
        return False
    if task.done():
        reasons.append(f"{name}: exited")
        return False
    return True


class _Readable(Protocol):
    def read(self) -> Reading: ...


class Heartbeat:
    """Checks in ``ok`` every ``interval_s`` while the gate reads fresh; silent otherwise."""

    def __init__(
        self,
        gate: _Readable,
        post: Callable[[dict[str, str]], int],
        *,
        build: str,
        interval_s: float | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._gate = gate
        self._post = post
        self._build = build
        self._interval_s = INTERVAL_SECONDS if interval_s is None else interval_s
        self._timeout_s = TIMEOUT_SECONDS if timeout_s is None else timeout_s
        # Set before a check-in thread starts; cleared by that thread once its
        # post returns, never by the timeout path (processor#39 trap 1, #45).
        self._in_flight = False
        # Whether the last tick checked in: an ok is logged only when it was not.
        self._ok = False

    async def run(self) -> None:
        """Tick every ``interval_s``, the first one interval in, until cancelled.

        Not at once (processor ticks at once): each start's first ``ok`` would
        then come before the process had proven it stays up, and a crash loop
        slower than ``StartLimitBurst=`` would never go silent (archiver#297
        review). A deploy's worst silence is still inside the grace
        (``docs/MONITORING.md`` § Liveness). Never raises: a tick that raises (a
        bug outside its own handlers) is logged with its traceback, and the next
        tick runs, so the heartbeat never ends silently.
        """
        next_tick = time.monotonic() + self._interval_s
        await asyncio.sleep(self._interval_s)
        while True:
            try:
                await self.tick()
            except Exception:
                self._ok = False
                logger.exception("liveness tick raised")
            next_tick += self._interval_s
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))

    async def tick(self) -> None:
        """One check-in, or a logged reason for none. Never raises but on cancel."""
        reading = self._gate.read()
        if not reading.fresh:
            self._ok = False
            logger.warning(
                "bus loops not progressing; not checking in",
                extra={"reasons": list(reading.reasons)},
            )
            return
        if self._in_flight:
            self._ok = False
            logger.warning("previous check-in still in flight; skipping this tick")
            return
        variables = {"build": self._build, **reading.variables}
        try:
            async with asyncio.timeout(self._timeout_s):
                code = await self._in_thread(variables)
        except TimeoutError:
            self._failed(f"timed out after {self._timeout_s} s")
            return
        except CheckinFailed as exc:
            self._failed(str(exc))
            return
        except Exception as exc:  # anything at all: never into the lifespan
            self._failed(f"{type(exc).__name__}: {exc}")
            return
        if not self._ok:
            logger.info("liveness check-in", extra={"checkin": code, **variables})
        self._ok = True

    def _failed(self, error: str) -> None:
        self._ok = False
        logger.warning("liveness check-in failed", extra={"error": error})

    def _in_thread(self, variables: dict[str, str]) -> asyncio.Future:
        """``post(variables)`` in a daemon thread; its future settles on the loop.

        Owns ``_in_flight``: set here before the thread starts, cleared by the
        thread once ``post`` returns and before the loop can see the result
        (processor#45). A post cut off by the timeout clears it only when it
        returns (processor#39 trap 1).
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def settle(result: object, error: BaseException | None) -> None:
            if future.done():  # cut off by the timeout, or cancelled
                return
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)

        def target() -> None:
            try:
                result, error = self._post(variables), None
            except BaseException as exc:
                result, error = None, exc
            self._in_flight = False  # before the loop can see the result (processor#45)
            try:
                loop.call_soon_threadsafe(settle, result, error)
            except RuntimeError:
                pass  # the loop closed while this thread waited on Status

        self._in_flight = True
        try:
            threading.Thread(target=target, name="liveness-checkin", daemon=True).start()
        except BaseException:
            self._in_flight = False  # no thread will clear it
            raise
        return future


def poster_from_env(environ: Mapping[str, str]) -> Callable[[dict[str, str]], int] | None:
    """The check-in to make each tick, or ``None`` when liveness is off.

    Says which once, at startup: ``liveness: on <id>``; ``liveness: off`` with no
    monitor id (a dev server, a test); at ERROR when the id is set but unusable or
    the key is missing. The service runs either way: an unmonitored service is
    better than one that will not start, and Status's silence pages regardless.
    """
    monitor_id = environ.get(MONITOR_ID_ENV, "")
    if not monitor_id:
        logger.info("liveness: off")
        return None
    if not MONITOR_ID_PATTERN.fullmatch(monitor_id):
        logger.error("liveness: off: %s is not a ULID", MONITOR_ID_ENV)
        return None
    credentials = environ.get("CREDENTIALS_DIRECTORY")
    try:
        key = read_key(Path(credentials) if credentials else None)
    except (OSError, ValueError):  # unreadable, or not text: never into the lifespan
        key = ""
    if not key:
        logger.error("liveness: off: missing the %s credential", CREDENTIAL_NAME)
        return None
    logger.info("liveness: on %s", monitor_id)
    base_url = environ.get(STATUS_URL_ENV) or DEFAULT_STATUS_URL
    return partial(post_checkin, base_url, monitor_id, key, "ok")
