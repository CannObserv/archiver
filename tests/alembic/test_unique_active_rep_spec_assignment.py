"""The partial unique index on active RepSpec assignments, and its pre-check (archiver#301).

``CREATE UNIQUE INDEX`` over rows that already collide fails with a bare
``UniqueViolation`` naming neither row. The migration looks first and refuses
with the colliding pairs, so the operator deactivates one and re-runs.

Drives the migration module's ``upgrade()`` under a real ``MigrationContext``,
as the archiver#276 rewrite test does. The suite's schema is already at head,
so each test drops the index first and leaves it in place on the way out.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "cdeb05831bd7_unique_active_rep_spec_assignment.py"
)
_INDEX = "uq_iirs_item_spec_active"


def _load_migration():
    spec = importlib.util.spec_from_file_location("_unique_active_assignment", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_upgrade(test_engine) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            module.upgrade()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


async def _index_exists(test_engine) -> bool:
    async with test_engine.connect() as conn:
        return bool(
            await conn.scalar(
                text(
                    "SELECT 1 FROM pg_indexes"
                    " WHERE schemaname = 'information' AND indexname = :name"
                ),
                {"name": _INDEX},
            )
        )


@pytest.fixture
async def rows(test_engine):
    """An item and a spec, committed; the index dropped. Restores both on teardown."""
    factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with factory() as s:
        item = InfoItem(name="iirs-unique-migration", rep_fields={})
        spec = RepSpec(
            provider="gcs",
            name="iirs-unique-migration",
            schema_version=1,
            document={"required_fields": []},
        )
        s.add_all([item, spec])
        await s.commit()
    async with test_engine.begin() as conn:
        await conn.execute(text(f"DROP INDEX information.{_INDEX}"))

    yield factory, item, spec

    async with factory() as s:
        await s.execute(delete(InfoItem).where(InfoItem.info_item_id == item.info_item_id))
        await s.execute(delete(RepSpec).where(RepSpec.rep_spec_id == spec.rep_spec_id))
        await s.commit()
    if not await _index_exists(test_engine):
        await _run_upgrade(test_engine)


async def _assign(factory, item, spec, *, active: bool = True) -> None:
    now = datetime.now(UTC)
    async with factory() as s:
        s.add(
            InfoItemRepSpec(
                info_item_id=item.info_item_id,
                rep_spec_id=spec.rep_spec_id,
                activated_at=now,
                deactivated_at=None if active else now,
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_existing_duplicates_refuse_the_upgrade_by_name(rows, test_engine):
    factory, item, spec = rows
    await _assign(factory, item, spec)
    await _assign(factory, item, spec)

    with pytest.raises(RuntimeError) as exc_info:
        await _run_upgrade(test_engine)

    message = str(exc_info.value)
    assert str(item.info_item_id) in message
    assert str(spec.rep_spec_id) in message
    assert not await _index_exists(test_engine)


@pytest.mark.asyncio
async def test_a_deactivated_twin_is_not_a_duplicate(rows, test_engine):
    factory, item, spec = rows
    await _assign(factory, item, spec)
    await _assign(factory, item, spec, active=False)

    await _run_upgrade(test_engine)

    assert await _index_exists(test_engine)
