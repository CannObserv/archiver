"""Tests for get_or_create_domain helper."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.core.models import Domain
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
