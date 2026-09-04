"""Connection policy for the long-lived Redis client the bus loops share.

Until archiver#193 this was ``RedisAsync.from_url(redis_url)`` with library
defaults, which loopback made harmless: a local broker either answers in
microseconds or refuses immediately. Neither is true across the tailnet hop to
the relocated broker (CannObserv/broker#1), where the measured path is a ~40 ms
DERP relay, so a *stalled* broker - as opposed to a refusing one - would hold a
consumer coroutine open with no bound. The process would stay up and
``/health`` would stay green, because ``/health`` is unauthenticated and DB-free
by contract and knows nothing about the bus.

**The binding constraint is the blocking read, and it points the opposite way
from intuition.** ``socket_timeout`` is not a stall bound to be set as tight as
nerves allow: redis-py does not extend it for a blocking command, so a value at
or below a loop's ``BLOCK`` window raises ``TimeoutError`` on every *idle* read
against a perfectly healthy broker. Measured on redis-py 7.4.1 against a local
broker: ``socket_timeout=1`` with ``XREAD ... BLOCK 3000`` raised after 1.01 s;
``socket_timeout=10`` returned normally after 3.08 s.

So the floor is the longest ``BLOCK`` of any loop sharing this client, and the
value is **derived from those constants** rather than transcribed beside a
comment naming them - the ``group_name()`` lesson from archiver#194. Raising a
loop's ``READ_BLOCK_MS`` moves the timeout with it; adding a loop with a longer
window is caught by ``tests/core/changes/test_bus_client.py``, which discovers
every ``READ_BLOCK_MS`` under this package rather than listing the ones known
today.

One thing this policy deliberately does not do is serialise the loops. The
client is shared, but ``from_url`` builds a pool, so each in-flight command holds
its own connection and a five-second blocking read does not sit in front of an
outbox ``XADD``.
"""

from __future__ import annotations

import time
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from redis.asyncio import Redis as RedisAsync
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

from src.core.changes import read_windows
from src.core.logging import get_logger

logger = get_logger(__name__)

# Headroom over the longest blocking read. It absorbs the round trip plus the
# broker's own scheduling slack, and it is the difference between "the read
# window elapsed" and "the socket is stalled". Five seconds is generous against
# a ~40 ms relayed path on purpose: the cost of being too tight is a spinning
# consumer, the cost of being too loose is noticing a stall five seconds later.
BLOCKING_READ_MARGIN_SECONDS = 5.0

# The longest window any loop on this client blocks for. Read from the leaf that
# owns the windows (``read_windows``) rather than from the consumer modules, so
# this module stays upstream of the loops that use its client - CR round 2,
# finding 13. The leaf's claim to be the longest is itself checked against every
# discovered loop in tests/core/changes/test_bus_client.py.
LONGEST_BLOCKING_READ_SECONDS = read_windows.LONGEST_READ_BLOCK_MS / 1000

SOCKET_TIMEOUT_SECONDS = LONGEST_BLOCKING_READ_SECONDS + BLOCKING_READ_MARGIN_SECONDS

# Connecting carries no BLOCK, so it needs no headroom and should fail fast: a
# broker that is down, mis-addressed, or black-holed by an ACL change is the
# case this bounds. Matches the value the bus-health probe already uses.
SOCKET_CONNECT_TIMEOUT_SECONDS = 5.0

# PING a connection that has been idle longer than this before reusing it, so a
# silently dropped TCP session surfaces as a retryable error on the next command
# instead of a first-write failure. Relevant across a relay in a way it never was
# on loopback, where nothing sits between the two ends to time a session out.
HEALTH_CHECK_INTERVAL_SECONDS = 30

# ZERO retries, stated rather than inherited. This client deliberately has no
# retry opinion, and an earlier draft of this module got it wrong (CR finding 3),
# so the reasoning is recorded rather than the value alone.
#
# **A redis-py retry re-sends the command, it does not resume the response.**
# ``Redis.execute_command`` wraps ``_send_command_parse_response`` in
# ``Retry.call_with_retry``, so a ``TimeoutError`` raised *after* the broker
# already applied an ``XADD`` publishes the entry a second time. That duplicate
# is invisible to the outbox: ``publish_attempts`` counts drain-loop attempts,
# not command-level ones, so the row's own diagnostics would understate what
# happened. ``content.replicate`` is the least tolerant consumer of a duplicate
# (MUST-4 absorbs it, but a second artifact in a permanent store has no way back
# - see ``replication_reaper``).
#
# Nothing is given up by declining it. Every loop already retries with escalating
# capped backoff (``src/core/changes/backoff.py``), the outbox is the durable
# buffer behind the publisher, and the stale-pooled-connection case a retry would
# have covered is what ``health_check_interval`` above is for. redis-py's own
# default is also zero - its stock ``Retry`` object reads as a policy and behaves
# as none - so this passes the value explicitly to make the zero a decision that
# a future reader has to argue with rather than a default they can assume away.
BUS_RETRIES = 0


def build_bus_client(redis_url: str) -> RedisAsync:
    """Build the shared bus client with an explicit connection policy.

    Raises ``ValueError`` on an empty URL rather than defaulting: an unset
    ``ARCHIVER_REDIS_URL`` means the service is bus-dormant, and that is the
    caller's branch to take. A client built from nothing would silently connect
    to whatever answers on the default host, which on the shared VM today is the
    production broker.
    """
    if not redis_url:
        raise ValueError("redis_url is required - an unset URL means bus-dormant, not localhost")
    return RedisAsync.from_url(
        redis_url,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=SOCKET_CONNECT_TIMEOUT_SECONDS,
        health_check_interval=HEALTH_CHECK_INTERVAL_SECONDS,
        # ``retry_on_error`` is deliberately absent: redis-py's Retry already
        # carries exactly (ConnectionError, TimeoutError), so passing the same
        # pair would imply this widens something it does not (CR finding 4).
        retry=Retry(ExponentialBackoff(), retries=BUS_RETRIES),
    )


# What an operator actually waits on an unreachable broker. ``socket_connect_timeout``
# bounds a single *attempt*; a retry would multiply it. Measured against a
# black-holed address on redis-py 7.4.1: connect=5/retries=0 raised at 5.01 s,
# connect=5/retries=1 at 10.03 s, connect=2/retries=1 at 4.02 s.
#
# At ``BUS_RETRIES = 0`` the two collapse, which is worth keeping expressed as
# the product anyway: the factor is what makes a retry added later cost twice
# what its own diff appears to say.
#
# This is why the probe below runs detached rather than inline in the lifespan:
# even five seconds of a blocked lifespan is five seconds the dashboard does not
# serve, and the dashboard has no business being unavailable because the bus is.
WORST_CASE_CONNECT_SECONDS = (BUS_RETRIES + 1) * SOCKET_CONNECT_TIMEOUT_SECONDS

_REDACTED = "***"


class SupportsPing(Protocol):
    """The only thing the probe needs from a client.

    Narrower than ``RedisAsync`` on purpose: it says what is actually required,
    and it lets the tests hand in a two-line stub without a type ignore.
    """

    async def ping(self) -> Any: ...


def redact_url(redis_url: str) -> str:
    """Return ``redis_url`` with any password replaced.

    The broker gains a credential when it moves to an authenticated node
    (CannObserv/broker#1 D3), and every line below goes to journald. Fails
    *closed*: a URL that will not parse is replaced wholesale rather than passed
    through, because the moment redaction is hardest is the moment a malformed
    URL is the thing being reported.

    The host is rebuilt rather than sliced out, which costs two edge cases worth
    naming (CR finding 5). ``urlsplit().hostname`` strips IPv6 brackets, so they
    have to be restored or the result stops being a URL; and it lower-cases,
    which is harmless for DNS but means the line is not byte-identical to what
    the operator configured. Both matter because ``redis_url`` is the one field
    identifying *which* broker is down, and it is emitted at ERROR mid-incident.
    """
    try:
        parts = urlsplit(redis_url)
        if parts.password is None:
            return redis_url
        host = parts.hostname or ""
        if ":" in host:  # IPv6 literal - urlsplit strips the brackets
            host = f"[{host}]"
        if parts.port:
            host = f"{host}:{parts.port}"
        userinfo = f"{parts.username or ''}:{_REDACTED}"
        return urlunsplit(
            (parts.scheme, f"{userinfo}@{host}", parts.path, parts.query, parts.fragment)
        )
    except ValueError:
        return "<unparseable redis url>"


async def probe_bus_reachable(client: SupportsPing, redis_url: str) -> bool:
    """PING the broker once and say so, loudly, either way.

    Closes the gap the epic names (archiver#193 Phase 1 item 3). ``from_url`` is
    **lazy** - verified: it returns in 0.000 s against a broker with nothing
    listening and raises nothing - so the lifespan's ``except Exception`` around
    publisher init never sees an unreachable broker. Startup succeeds, the
    publisher task is scheduled, and the first real failure lands later inside a
    loop that correctly treats it as transient and backs off quietly behind
    ``ERROR_LOG_EVERY``. Correct behaviour for a *partition*; indistinguishable
    from an idle cluster for a *misconfiguration*.

    Never raises. It is spawned detached, so an exception here would surface as a
    bare "Task exception was never retrieved" and set the diagnosis back.
    ``BaseException`` is deliberately not caught: a ``CancelledError`` at
    shutdown must propagate or the task will not stop.
    """
    started = time.monotonic()
    try:
        await client.ping()
    except Exception as e:
        logger.error(
            "Bus broker is configured but unreachable - the bus is NOT idle, it is down",
            extra={
                "redis_url": redact_url(redis_url),
                "error": f"{type(e).__name__}: {e}",
                "waited_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return False
    logger.info(
        "Bus broker reachable",
        extra={
            "redis_url": redact_url(redis_url),
            "rtt_ms": round((time.monotonic() - started) * 1000),
        },
    )
    return True
