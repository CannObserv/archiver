"""Tests for /dashboard/ home page (Epic 7 + #49 redesign)."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_ARTIFACTS, CONTENT_REVISIONS
from fakeredis import aioredis as fakeredis_aio

from src.api.deps import get_redis_client
from src.api.main import app
from src.core.bus_health import STREAM_CHECKS
from src.core.changes.artifacts_consumer import CONSUMER_GROUP as ARTIFACTS_GROUP
from src.core.changes.consumer import CONSUMER_GROUP as REVISIONS_GROUP
from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemSource,
    InfoSource,
    SourceRevision,
)
from src.core.models.domain import Domain
from src.dashboard.routes import index as index_routes

_HEADERS = {"X-ExeDev-UserID": "ext-home", "X-ExeDev-Email": "home@example.com"}


def _make_source(url: str) -> InfoSource:
    return InfoSource(
        url=url,
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )


@pytest.mark.asyncio
async def test_home_unauthenticated_redirects(client):
    r = await client.get("/dashboard/", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_returns_200(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_home_shows_register_cta(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Register Information Item" in r.text
    assert "/dashboard/register" in r.text


@pytest.mark.asyncio
async def test_home_shows_browse_info_items_link(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Browse Information Items" in r.text
    assert "/dashboard/info-items/" in r.text


@pytest.mark.asyncio
async def test_home_shows_entity_counts(client, session):
    session.add(InfoItem(name="Count Item"))
    src = _make_source("https://example.com/count-src")
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "1" in r.text


@pytest.mark.asyncio
async def test_health_partial_returns_badge(client):
    r = await client.get("/dashboard/health", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "badge" in r.text
    assert "ok" in r.text


@pytest.mark.asyncio
async def test_health_partial_unauthenticated_redirects(client):
    r = await client.get("/dashboard/health", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_shows_recent_activity(client, session):
    src = _make_source("https://example.com/recent-rev")
    session.add(src)
    await session.flush()
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "2026-05-01" in r.text
    assert "Recent Activity" in r.text
    assert "Item" in r.text
    assert "Source" in r.text
    assert "Revision" in r.text
    assert "Observed" in r.text
    url_pos = r.text.index("example.com/recent-rev")
    fp_pos = r.text.index("sha256:ffffffff")
    assert url_pos < fp_pos


@pytest.mark.asyncio
async def test_home_recent_activity_shows_item_name_when_bound(client, session):
    """When a revision is bound to an InfoItem, the Item column shows the item name."""
    src = _make_source("https://example.com/item-activity")
    item = InfoItem(name="Activity Item")
    session.add_all([src, item])
    await session.flush()
    binding = InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)
    session.add(binding)
    rev = SourceRevision(
        info_source_id=src.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
    )
    session.add(rev)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "Activity Item" in r.text


@pytest.mark.asyncio
async def test_health_redis_ok(client):
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    r = await client.get("/dashboard/health/redis", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--success" in r.text


@pytest.mark.asyncio
async def test_health_redis_degraded(client):
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(side_effect=Exception("timed out"))
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    r = await client.get("/dashboard/health/redis", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "timed out" in r.text


@pytest.mark.asyncio
async def test_health_redis_not_configured(client):
    app.dependency_overrides[get_redis_client] = lambda: None
    r = await client.get("/dashboard/health/redis", headers=_HEADERS)
    assert r.status_code == 200
    assert "not configured" in r.text.lower()


@pytest.mark.asyncio
async def test_health_redis_unauthenticated_redirects(client):
    r = await client.get("/dashboard/health/redis", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_domain_overview_appears_when_domains_exist(client, session):
    """Domain overview table renders when domains + sources exist."""
    domain = Domain(name="overview.example.com")
    session.add(domain)
    await session.flush()
    src = InfoSource(
        url="https://overview.example.com/path",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
        domain_name="overview.example.com",
    )
    session.add(src)
    await session.flush()

    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "overview.example.com" in r.text
    assert "Domains" in r.text


def _configure_bus():
    """Simulate a configured bus (publisher running) for the outbox badge.

    The badge's drain-state vocabulary (ok / backlog / dead-lettered) only
    means anything while something drains; with no Redis client the route
    renders the dormant state instead (CR round 1, finding 1).
    """
    app.dependency_overrides[get_redis_client] = lambda: MagicMock()


@pytest.mark.asyncio
async def test_health_outbox_ok_when_empty(client, session):
    _configure_bus()
    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--success" in r.text
    assert "ok" in r.text


@pytest.mark.asyncio
async def test_health_outbox_dormant_when_bus_unconfigured(client, session):
    """No Redis client = publisher not running: rows cannot drain, so a stale
    backlog is the configured-off state, not ill health - muted, no warning
    (the dev server is bus-dormant by design)."""
    app.dependency_overrides[get_redis_client] = lambda: None
    session.add(
        ChangesOutboxRow(
            topic="info.changes",
            payload={"event_type": "irrelevant"},
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--muted" in r.text
    assert "not draining" in r.text
    assert "badge--warning" not in r.text


@pytest.mark.asyncio
async def test_health_outbox_warns_on_stale_backlog(client, session):
    """A live unpublished row older than the warn threshold renders a warning
    badge - the drain is not keeping up (or Redis is down)."""
    _configure_bus()
    session.add(
        ChangesOutboxRow(
            topic="info.changes",
            payload={"event_type": "irrelevant"},
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--warning" in r.text
    assert "backlog" in r.text


@pytest.mark.asyncio
async def test_health_outbox_fresh_backlog_is_ok(client, session):
    """A young unpublished row is normal operation, not a warning."""
    _configure_bus()
    session.add(
        ChangesOutboxRow(
            topic="info.changes",
            payload={"event_type": "irrelevant"},
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--success" in r.text


@pytest.mark.asyncio
async def test_health_outbox_danger_on_dead_lettered(client, session):
    """Any dead-lettered row is an operator signal - danger badge with the count."""
    _configure_bus()
    session.add(
        ChangesOutboxRow(
            topic="info.changes",
            payload={"event_type": "poison"},
            created_at=datetime.now(UTC),
            dead_lettered_at=datetime.now(UTC),
        )
    )
    await session.flush()

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "1 dead-lettered" in r.text


@pytest.mark.asyncio
async def test_health_outbox_unauthenticated_redirects(client):
    r = await client.get("/dashboard/health/outbox", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_shows_outbox_health_slot(client):
    """The home health strip carries the outbox badge loader."""
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "/dashboard/health/outbox" in r.text


# --- consumer liveness + group lag (archiver#147) ---
#
# The badge #147 exists for. Before it, one env-var boolean covered three
# states an operator cannot otherwise tell apart: gated off, gated on but dead,
# and healthy. Each of the first two gets its own test here, because "green
# while revisions are silently piling up" is the exact failure being closed.


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    yield r
    await r.aclose()


def _live_task():
    task = MagicMock()
    task.done.return_value = False
    return task


def _dead_task(exc=RuntimeError("consumer crashed")):
    task = MagicMock()
    task.done.return_value = True
    task.exception.return_value = exc
    return task


def _consumers(monkeypatch, redis, *, revisions, artifacts, gate="1"):
    """Put the app in the state a given lifespan branch leaves behind."""
    if gate is None:
        monkeypatch.delenv("ARCHIVER_BUS_CONSUMER", raising=False)
    else:
        monkeypatch.setenv("ARCHIVER_BUS_CONSUMER", gate)
    monkeypatch.setattr(app.state, "revisions_consumer_task", revisions, raising=False)
    monkeypatch.setattr(app.state, "artifacts_consumer_task", artifacts, raising=False)
    app.dependency_overrides[get_redis_client] = lambda: redis


_GROUPS = ((CONTENT_REVISIONS, REVISIONS_GROUP), (CONTENT_ARTIFACTS, ARTIFACTS_GROUP))


async def _provision_groups(redis):
    """What a healthy consumer startup leaves on the broker."""
    for topic, group in _GROUPS:
        await redis.xgroup_create(topic, group, id="0", mkstream=True)


@pytest.mark.asyncio
async def test_health_consumers_not_configured_without_a_broker(client, monkeypatch):
    _consumers(monkeypatch, None, revisions=None, artifacts=None, gate=None)
    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--muted" in r.text
    assert "not configured" in r.text


@pytest.mark.asyncio
async def test_health_consumers_muted_when_gated_off(client, monkeypatch, fake_redis):
    """State 1 of the issue: a broker is configured but ARCHIVER_BUS_CONSUMER is
    unset, so no consumer is running *by design* (the dev server's default).
    Deliberately off is muted, not a warning - the same vocabulary the outbox
    badge uses for a dormant publisher."""
    _consumers(monkeypatch, fake_redis, revisions=None, artifacts=None, gate=None)
    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--muted" in r.text
    assert "gated off" in r.text


@pytest.mark.asyncio
async def test_health_consumers_danger_when_never_started(client, monkeypatch, fake_redis):
    """Gated on but no task handle: the lifespan's init raised and logged, and
    nothing has consumed since. Previously indistinguishable from healthy."""
    _consumers(monkeypatch, fake_redis, revisions=None, artifacts=_live_task())
    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "not started" in r.text


@pytest.mark.asyncio
async def test_health_consumers_danger_when_a_task_has_exited(client, monkeypatch, fake_redis):
    """State 2 of the issue, the one that silently loses ground: the loop exited
    while content.revisions keeps growing. The exit reason rides the title."""
    _consumers(monkeypatch, fake_redis, revisions=_dead_task(), artifacts=_live_task())
    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "stopped" in r.text
    assert "consumer crashed" in r.text


@pytest.mark.asyncio
async def test_health_consumers_tolerates_a_cancelled_task(client, monkeypatch, fake_redis):
    """``Task.exception()`` *raises* on a cancelled task rather than returning.
    Shutdown cancels these tasks, so the badge must render the stop, not a 500."""
    cancelled = MagicMock()
    cancelled.done.return_value = True
    cancelled.exception.side_effect = asyncio.CancelledError()
    _consumers(monkeypatch, fake_redis, revisions=cancelled, artifacts=_live_task())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "stopped" in r.text


@pytest.mark.asyncio
async def test_health_consumers_danger_on_a_nonempty_dlq(client, monkeypatch, fake_redis):
    """Every DLQ entry is a frame the registry decided it could never use, so it
    is operator-actionable even while both consumers run normally."""
    await _provision_groups(fake_redis)
    await fake_redis.xadd("content.revisions.dlq", {"k": "v"})
    _consumers(monkeypatch, fake_redis, revisions=_live_task(), artifacts=_live_task())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "1 dead-lettered" in r.text


@pytest.mark.asyncio
async def test_health_consumers_warns_on_group_lag(client, monkeypatch, fake_redis):
    await _provision_groups(fake_redis)
    await fake_redis.xadd(CONTENT_REVISIONS, {"k": "v"})
    await fake_redis.xreadgroup(REVISIONS_GROUP, "c1", {CONTENT_REVISIONS: ">"}, count=10)
    _consumers(monkeypatch, fake_redis, revisions=_live_task(), artifacts=_live_task())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--warning" in r.text
    assert "lagging" in r.text


@pytest.mark.asyncio
async def test_health_consumers_warns_when_a_group_is_missing(client, monkeypatch, fake_redis):
    """A live task whose group does not exist consumed nothing and never will;
    rendering the absent group as a healthy pending=0 is the bug, not a nicety."""
    _consumers(monkeypatch, fake_redis, revisions=_live_task(), artifacts=_live_task())
    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--warning" in r.text
    assert "group missing" in r.text


@pytest.mark.asyncio
async def test_health_consumers_warns_when_the_broker_cannot_be_probed(client, monkeypatch):
    """Liveness comes from app.state and stays true, but the lag numbers are
    unavailable - which must not read as measured zeroes."""

    class DownRedis:
        def __getattr__(self, name):
            async def _raise(*a, **kw):
                raise ConnectionError("refused")

            return _raise

    _consumers(monkeypatch, DownRedis(), revisions=_live_task(), artifacts=_live_task())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--warning" in r.text
    assert "lag unknown" in r.text


@pytest.mark.asyncio
async def test_health_consumers_ok_when_running_and_drained(client, monkeypatch, fake_redis):
    await _provision_groups(fake_redis)
    _consumers(monkeypatch, fake_redis, revisions=_live_task(), artifacts=_live_task())

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--success" in r.text
    assert "running" in r.text
    assert "pending=0" in r.text


@pytest.mark.asyncio
async def test_health_consumers_unauthenticated_redirects(client):
    r = await client.get("/dashboard/health/consumers", follow_redirects=False)
    assert r.status_code == 307


@pytest.mark.asyncio
async def test_home_shows_consumer_health_slot(client):
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "/dashboard/health/consumers" in r.text


@pytest.mark.asyncio
async def test_home_redis_badge_always_loads_live(client, monkeypatch):
    """The strip no longer branches on ``ARCHIVER_REDIS_URL`` to decide what to
    render - reporting configuration as if it were state is the whole of #147.
    Every badge is now a live route, and "not configured" is that route's
    answer rather than a template-side guess."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    r = await client.get("/dashboard/", headers=_HEADERS)
    assert r.status_code == 200
    assert "/dashboard/health/redis" in r.text


# --- CR round 1 on #147 ---


@pytest.mark.asyncio
async def test_health_consumers_bounds_a_hung_broker(client, monkeypatch):
    """Finding 1. The lifespan client carries no socket timeout - it cannot,
    since the group consumers issue a blocking XREADGROUP on it - so a broker
    that hangs rather than refuses would block this handler forever and the
    "lag unknown" state would never be reached. The bound lives at the call
    site instead."""

    class HungRedis:
        def __getattr__(self, name):
            async def _hang(*a, **kw):
                await asyncio.sleep(30)

            return _hang

    monkeypatch.setattr(index_routes, "LAG_PROBE_TIMEOUT_SECONDS", 0.05)
    _consumers(monkeypatch, HungRedis(), revisions=_live_task(), artifacts=_live_task())

    r = await asyncio.wait_for(
        client.get("/dashboard/health/consumers", headers=_HEADERS), timeout=5
    )
    assert r.status_code == 200
    assert "badge--warning" in r.text
    assert "lag unknown" in r.text


@pytest.mark.asyncio
async def test_health_consumers_does_not_mask_a_programming_error(client, monkeypatch, fake_redis):
    """Finding 2. A bug inside the probe must not render as "lag unknown" - that
    reads as a broker condition and sends the operator to the wrong system."""

    async def _boom(_client):
        raise TypeError("probe bug, not a broker state")

    monkeypatch.setattr(index_routes, "collect_group_lag", _boom)
    _consumers(monkeypatch, fake_redis, revisions=_live_task(), artifacts=_live_task())

    with pytest.raises(TypeError):
        await client.get("/dashboard/health/consumers", headers=_HEADERS)


@pytest.mark.asyncio
async def test_health_consumers_init_failure_is_not_not_configured(client, monkeypatch):
    """Finding 3. main.py nulls app.state.redis_client when publisher init
    *raises* with ARCHIVER_REDIS_URL set. Reporting that as "not configured" is
    the configuration-as-state conflation #147 exists to remove, surviving in a
    rarer branch."""
    monkeypatch.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/0")
    _consumers(monkeypatch, None, revisions=None, artifacts=None, gate="1")

    r = await client.get("/dashboard/health/consumers", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "init failed" in r.text


@pytest.mark.asyncio
async def test_health_redis_init_failure_is_not_not_configured(client, monkeypatch):
    """Finding 3, the same gap on the pre-existing Redis badge."""
    monkeypatch.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/0")
    app.dependency_overrides[get_redis_client] = lambda: None

    r = await client.get("/dashboard/health/redis", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "init failed" in r.text


@pytest.mark.asyncio
async def test_health_redis_unconfigured_stays_muted(client, monkeypatch):
    """The other side of finding 3: no URL really is not configured."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    app.dependency_overrides[get_redis_client] = lambda: None

    r = await client.get("/dashboard/health/redis", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--muted" in r.text
    assert "not configured" in r.text


def test_consumer_badge_covers_every_archiver_owned_group():
    """Finding 4. The ladder's DLQ and pending checks iterate the lag list,
    sourced from STREAM_CHECKS, while the title is built from _CONSUMERS. Let
    those sets drift and the badge reports a state its title cannot explain."""
    assert {topic for _name, _attr, topic in index_routes._CONSUMERS} == {
        check.topic for check in STREAM_CHECKS if check.pending_group is not None
    }


# --- CR round 2 on #147 ---


@pytest.mark.asyncio
async def test_health_outbox_init_failure_is_not_dormant(client, session, monkeypatch):
    """Finding 10. The outbox badge collapsed both no-client causes into muted
    "not draining". Publisher-init-raised is exactly when a stale backlog *is*
    ill health, which is the opposite of what muted tells the operator."""
    monkeypatch.setenv("ARCHIVER_REDIS_URL", "redis://localhost:6379/0")
    app.dependency_overrides[get_redis_client] = lambda: None

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--danger" in r.text
    assert "init failed" in r.text


@pytest.mark.asyncio
async def test_health_outbox_dormant_stays_muted_without_a_url(client, session, monkeypatch):
    """The other side of finding 10: no URL is the dev server's bus-dormant
    default, and a stale backlog there is the configured-off state."""
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    app.dependency_overrides[get_redis_client] = lambda: None

    r = await client.get("/dashboard/health/outbox", headers=_HEADERS)
    assert r.status_code == 200
    assert "badge--muted" in r.text
    assert "not draining" in r.text


@pytest.mark.asyncio
async def test_health_consumers_timeout_title_names_the_bound(client, monkeypatch):
    """Finding 11. str(TimeoutError()) is empty, so the title fell back to
    repr() and read "TimeoutError()" - no duration, no cause. A wedged broker
    and a refused connection render the same badge, so the title is the only
    place they can be told apart."""

    class HungRedis:
        def __getattr__(self, name):
            async def _hang(*a, **kw):
                await asyncio.sleep(30)

            return _hang

    monkeypatch.setattr(index_routes, "LAG_PROBE_TIMEOUT_SECONDS", 0.05)
    _consumers(monkeypatch, HungRedis(), revisions=_live_task(), artifacts=_live_task())

    r = await asyncio.wait_for(
        client.get("/dashboard/health/consumers", headers=_HEADERS), timeout=5
    )
    assert "lag unknown" in r.text
    assert "exceeded 0.05s" in r.text
    assert "TimeoutError()" not in r.text
