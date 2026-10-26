"""get_or_create_domain — upsert a Domain row by hostname.

Called at InfoSource write time; caller commits the surrounding transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.domain import Domain
from src.core.services.fetch_policy import announce_domain


async def get_or_create_domain(db: AsyncSession, hostname: str) -> Domain:
    """Return existing Domain for *hostname*, creating one if absent.

    Uses an INSERT ... ON CONFLICT DO NOTHING to handle concurrent inserts
    safely. Caller is responsible for committing.

    A row this call inserts is a new host on ``content.fetch-policy``
    (archiver#366): ``announce_domain`` redraws its generation now that the
    row is this transaction's - above any tombstone a racing delete drew - and
    clears that tombstone.
    """
    stmt = (
        pg_insert(Domain)
        .values(name=hostname)
        .on_conflict_do_nothing(index_elements=["name"])
        .returning(Domain.id)
    )
    inserted = (await db.execute(stmt)).first() is not None

    result = await db.execute(select(Domain).where(Domain.name == hostname))
    domain = result.scalar_one()
    if inserted:
        await announce_domain(db, domain)
    return domain
