"""``uq_iirs_item_spec_active`` is the one active-row index on assignments (archiver#311).

``ix_iirs_item_active (info_item_id) WHERE deactivated_at IS NULL`` became
redundant when archiver#301 added the unique index: same predicate, same
leading column. Its migration drops it; the downgrade puts it back.

The EXPLAIN tests pin that item-only active lookups still have an index to
use. ``enable_seqscan`` is off because the table is tiny: left on, the planner
seq-scans and the plan proves nothing about which index would serve.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from src.core.models import InfoItemRepSpec

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "7c4e1f2a9b30_drop_ix_iirs_item_active.py"
)
_DROPPED = "ix_iirs_item_active"
_SURVIVOR = "uq_iirs_item_spec_active"


def _load_migration():
    spec = importlib.util.spec_from_file_location("_drop_ix_iirs_item_active", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(test_engine, step: str) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            getattr(module, step)()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


async def _active_row_indexes(test_engine) -> set[str]:
    async with test_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes"
                " WHERE schemaname = 'information' AND tablename = 'info_item_rep_specs'"
                "   AND indexdef LIKE '%deactivated_at IS NULL%'"
            )
        )
        return {name for (name,) in rows}


async def _plan(test_engine, sql: str) -> str:
    async with test_engine.begin() as conn:
        await conn.execute(text("SET LOCAL enable_seqscan = off"))
        rows = await conn.execute(text(f"EXPLAIN {sql}"))
        return "\n".join(line for (line,) in rows)


def test_model_declares_one_active_row_index():
    names = {index.name for index in InfoItemRepSpec.__table__.indexes}
    assert _DROPPED not in names
    assert _SURVIVOR in names


@pytest.mark.asyncio
async def test_head_has_one_active_row_index(test_engine):
    assert await _active_row_indexes(test_engine) == {_SURVIVOR}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "predicate",
    [
        "info_item_id = '01J00000000000000000000000'",
        "info_item_id IN ('01J00000000000000000000000', '01J00000000000000000000001')",
    ],
    ids=["one-item", "item-batch"],
)
async def test_item_only_active_lookup_uses_the_unique_index(test_engine, predicate):
    plan = await _plan(
        test_engine,
        "SELECT * FROM information.info_item_rep_specs"
        f" WHERE {predicate} AND deactivated_at IS NULL",
    )
    assert _SURVIVOR in plan


@pytest.mark.asyncio
async def test_downgrade_recreates_the_index_and_upgrade_drops_it(test_engine):
    await _run(test_engine, "downgrade")
    try:
        assert await _active_row_indexes(test_engine) == {_DROPPED, _SURVIVOR}
    finally:
        await _run(test_engine, "upgrade")
    assert await _active_row_indexes(test_engine) == {_SURVIVOR}
