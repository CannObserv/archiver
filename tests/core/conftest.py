"""Fixtures shared by the #369 dispatch tests under ``tests/core``."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.core.services._dispatch_seed import TRUNCATE


@pytest.fixture
def session_factory(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
async def clean_dispatch_tables(test_engine):
    async def _truncate() -> None:
        async with test_engine.begin() as conn:
            for statement in TRUNCATE:
                await conn.execute(text(statement))

    await _truncate()
    yield
    await _truncate()
