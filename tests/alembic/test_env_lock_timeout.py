"""A migration that cannot get its lock fails fast instead of queueing (archiver#348).

``lock_timeout`` is 0 cluster-wide, so before #348 a migration blocked by any
open reader - an agent's long ``SELECT``, a transaction left idle - waited
forever, and every API query queued behind its pending ``ACCESS EXCLUSIVE``.
Role-level ``statement_timeout`` on a reader cannot prevent that: a session
can ``SET`` it back to 0. The bound belongs to the migrator. Failing, it is
``deploy.sh``'s "migration failed; nothing switched".
"""

import asyncio
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _upgrade_head() -> None:
    alembic_command.upgrade(AlembicConfig(str(_INI)), "head")


@pytest.mark.asyncio
async def test_a_held_lock_fails_the_migration_within_seconds(test_engine):
    """At head the upgrade still reads ``alembic_version``; an exclusive lock blocks it."""
    async with test_engine.connect() as holder:
        await holder.begin()
        await holder.execute(text("LOCK TABLE information.alembic_version IN ACCESS EXCLUSIVE MODE"))
        try:
            with pytest.raises(DBAPIError, match="lock timeout"):
                await asyncio.wait_for(asyncio.to_thread(_upgrade_head), timeout=30)
        finally:
            await holder.rollback()
