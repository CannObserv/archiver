"""Tests for get_or_create_domain helper."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.core.models import ChangesOutboxRow, Domain, FetchPolicyTombstone
from src.core.services import fetch_policy
from src.core.tools.get_or_create_domain import get_or_create_domain


@pytest.mark.asyncio
async def test_creates_domain_when_absent(session):
    domain = await get_or_create_domain(session, "example.com")
    await session.flush()
    result = await session.execute(select(Domain).where(Domain.name == "example.com"))
    row = result.scalar_one()
    assert row.name == "example.com"
    assert domain.name == "example.com"


@pytest.mark.asyncio
async def test_returns_existing_domain(session):
    d1 = await get_or_create_domain(session, "regulations.cannabis.ca.gov")
    await session.flush()
    d2 = await get_or_create_domain(session, "regulations.cannabis.ca.gov")
    await session.flush()
    assert d1.name == d2.name


@pytest.mark.asyncio
async def test_domain_defaults_active(session):
    domain = await get_or_create_domain(session, "new-domain.example.org")
    await session.flush()
    assert domain.is_active is True
    assert domain.archived_at is None


# --- content.fetch-policy (archiver#366) -------------------------------------


@pytest.mark.asyncio
async def test_a_new_host_draws_above_its_tombstone_and_clears_it(session, monkeypatch):
    """A source created on a deleted host is a re-add: the live frame must
    order above the delete's tombstone, or every consumer drops it."""
    monkeypatch.setenv(fetch_policy.PRODUCER_ENV, "1")
    tombstone_gen = await fetch_policy.announce_domain_deleted(session, "readd.example.com")

    domain = await get_or_create_domain(session, "readd.example.com")

    assert domain.fetch_policy_generation > tombstone_gen
    assert (
        await session.execute(
            select(FetchPolicyTombstone).where(FetchPolicyTombstone.host == "readd.example.com")
        )
    ).scalar_one_or_none() is None
    frames = (
        (
            await session.execute(
                select(ChangesOutboxRow.payload)
                .where(ChangesOutboxRow.topic == fetch_policy.FETCH_POLICY_TOPIC)
                .where(ChangesOutboxRow.payload["host"].astext == "readd.example.com")
                .order_by(ChangesOutboxRow.created_at, ChangesOutboxRow.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(f["revoked"], f["generation"]) for f in frames] == [
        (True, tombstone_gen),
        (False, domain.fetch_policy_generation),
    ]


@pytest.mark.asyncio
async def test_an_existing_host_draws_nothing(session):
    first = await get_or_create_domain(session, "same.example.com")
    generation = first.fetch_policy_generation
    again = await get_or_create_domain(session, "same.example.com")
    assert again.fetch_policy_generation == generation
