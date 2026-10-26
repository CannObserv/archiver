"""The ``content.fetch-policy`` delta half (archiver#366).

Generations are drawn from one sequence whenever a host's frame changes, flag
or no flag; outbox rows are written only while the producer is enabled.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.core.models import ChangesOutboxRow, FetchPolicyTombstone
from src.core.models.domain import Domain
from src.core.services import fetch_policy
from src.core.services.fetch_policy import (
    FETCH_POLICY_TOPIC,
    PRODUCER_ENV,
    announce_domain,
    announce_domain_deleted,
    build_domain_policy,
    build_policy,
    policy_frame,
    producer_enabled,
)

HOST = "fp.example.test"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(PRODUCER_ENV, "1")


@pytest.fixture
def dark(monkeypatch):
    monkeypatch.delenv(PRODUCER_ENV, raising=False)


async def _domain(session, name: str = HOST, **kw) -> Domain:
    domain = Domain(name=name, **kw)
    session.add(domain)
    await session.flush()
    return domain


async def _rows(session, host: str = HOST) -> list[dict]:
    rows = (
        (
            await session.execute(
                select(ChangesOutboxRow)
                .where(
                    ChangesOutboxRow.topic == FETCH_POLICY_TOPIC,
                    ChangesOutboxRow.payload["host"].astext == host,
                )
                .order_by(ChangesOutboxRow.created_at, ChangesOutboxRow.id)
            )
        )
        .scalars()
        .all()
    )
    return [r.payload for r in rows]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, False), ("", False), ("0", False), ("no", False), ("1", True), (" TRUE ", True)],
)
def test_producer_enabled_parses_the_unit_flag(raw, expected):
    environ = {} if raw is None else {PRODUCER_ENV: raw}
    assert producer_enabled(environ) is expected


def test_producer_enabled_reads_the_environment_by_default(monkeypatch):
    monkeypatch.setenv(PRODUCER_ENV, "1")
    assert producer_enabled() is True
    monkeypatch.delenv(PRODUCER_ENV)
    assert producer_enabled() is False


def test_topic_is_co_cores():
    assert FETCH_POLICY_TOPIC == "content.fetch-policy"


# --- the guard: no frame without a generation --------------------------------


@pytest.mark.parametrize("generation", [None, -1, "7", 1.5, True])
def test_build_policy_refuses_a_frame_without_an_integer_generation(generation):
    """``FetchPolicyEmit`` accepts ``generation=None`` until cannobserv#579, and a
    frame without one is dropped silently by every consumer that holds an
    ordered frame. So the one builder refuses it."""
    with pytest.raises((TypeError, ValueError)):
        build_policy(host=HOST, generation=generation, min_interval_seconds=1.0, revoked=False)


def test_build_policy_tombstone_carries_its_generation_and_no_interval():
    event = build_policy(host=HOST, generation=9, min_interval_seconds=None, revoked=True)
    assert event.generation == 9
    assert event.revoked is True
    assert event.min_interval_seconds is None


# --- the frame ---------------------------------------------------------------


def test_active_host_frame_is_its_interval():
    assert policy_frame(Domain(name=HOST, is_active=True, min_interval_seconds=2.5)) == (
        False,
        2.5,
    )


@pytest.mark.parametrize(
    "kw",
    [{"is_active": False}, {"is_active": True, "archived_at": datetime(2026, 1, 1, tzinfo=UTC)}],
)
def test_suspended_host_frame_is_revoked_without_a_number(kw):
    """Watcher's #250 rule: never a fake number on a revoked frame."""
    assert policy_frame(Domain(name=HOST, min_interval_seconds=2.5, **kw)) == (True, None)


@pytest.mark.asyncio
async def test_build_domain_policy_uses_the_stored_generation(session):
    domain = await _domain(session, min_interval_seconds=3.0)
    event = build_domain_policy(domain)
    assert event.host == HOST
    assert event.generation == domain.fetch_policy_generation
    assert (event.revoked, event.min_interval_seconds) == (False, 3.0)


# --- announce_domain ---------------------------------------------------------


@pytest.mark.asyncio
async def test_announce_draws_a_higher_generation_and_queues_the_frame(session, enabled):
    domain = await _domain(session, min_interval_seconds=2.0)
    before = domain.fetch_policy_generation

    await announce_domain(session, domain)

    assert domain.fetch_policy_generation > before
    stored = (
        await session.execute(select(Domain.fetch_policy_generation).where(Domain.name == HOST))
    ).scalar_one()
    assert stored == domain.fetch_policy_generation
    [payload] = await _rows(session)
    assert payload["event_type"] == "fetch_policy"
    assert payload["generation"] == domain.fetch_policy_generation
    assert payload["min_interval_seconds"] == 2.0
    assert payload["revoked"] is False


@pytest.mark.asyncio
async def test_announce_while_dark_still_draws_but_queues_nothing(session, dark):
    """D1: generations keep advancing while dark, so the first full set at F1
    carries current values; nothing reaches the outbox."""
    domain = await _domain(session)
    before = domain.fetch_policy_generation

    await announce_domain(session, domain)

    assert domain.fetch_policy_generation > before
    assert await _rows(session) == []


@pytest.mark.asyncio
async def test_announce_clears_the_hosts_tombstone(session, dark):
    session.add(FetchPolicyTombstone(host=HOST, generation=1))
    await session.flush()
    domain = await _domain(session)

    await announce_domain(session, domain)

    assert (
        await session.execute(select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == HOST))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_announce_skips_an_unpublishable_host_without_failing_the_write(
    session, enabled, caplog
):
    """Watcher's rule: one bad host must not fail the write. ``Domain.name`` is
    canonical by the time it gets here, so this is a backstop."""
    domain = await _domain(session, name="bad host.example.test")

    await announce_domain(session, domain)

    assert await _rows(session, "bad host.example.test") == []
    assert "unpublishable" in caplog.text


# --- announce_domain_deleted -------------------------------------------------


@pytest.mark.asyncio
async def test_delete_records_a_tombstone_above_the_hosts_generation(session, enabled):
    domain = await _domain(session)
    live = domain.fetch_policy_generation

    generation = await announce_domain_deleted(session, HOST)

    assert generation > live
    tombstone = (
        await session.execute(select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == HOST))
    ).scalar_one()
    assert tombstone.generation == generation
    [payload] = await _rows(session)
    assert payload["revoked"] is True
    assert payload["min_interval_seconds"] is None
    assert payload["generation"] == generation


@pytest.mark.asyncio
async def test_a_second_delete_moves_the_tombstone_up(session, dark):
    first = await announce_domain_deleted(session, HOST)
    second = await announce_domain_deleted(session, HOST)
    assert second > first
    tombstone = (
        await session.execute(select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == HOST))
    ).scalar_one()
    assert tombstone.generation == second


@pytest.mark.asyncio
async def test_delete_while_dark_records_the_tombstone_and_queues_nothing(session, dark):
    await announce_domain_deleted(session, HOST)
    assert await _rows(session) == []
    assert (
        await session.execute(select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == HOST))
    ).scalar_one() is not None


def test_build_tombstone_is_revoked_at_its_generation():
    event = fetch_policy.build_tombstone(host=HOST, generation=11)
    assert (event.host, event.generation, event.revoked) == (HOST, 11, True)
    assert event.min_interval_seconds is None
