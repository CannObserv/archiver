"""get_or_create_domain — upsert a Domain row by hostname.

Called at InfoSource write time; caller commits the surrounding transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.domain import Domain


async def get_or_create_domain(db: AsyncSession, hostname: str) -> Domain:
    """Return existing Domain for *hostname*, creating one if absent.

    Uses an INSERT ... ON CONFLICT DO NOTHING to handle concurrent inserts
    safely. Caller is responsible for committing.
    """
    stmt = pg_insert(Domain).values(name=hostname).on_conflict_do_nothing(index_elements=["name"])
    await db.execute(stmt)

    result = await db.execute(select(Domain).where(Domain.name == hostname))
    return result.scalar_one()
