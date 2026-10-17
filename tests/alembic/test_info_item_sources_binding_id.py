"""``info_item_sources`` is one row per tenure, keyed by a ULID ``id`` (archiver#392).

The composite ``(info_item_id, info_source_id)`` key held one row per pair, so a
swap back to a previous primary could only reactivate that row, erasing the
first tenure's end. The migration backfills ``id`` from each row's
``created_at``, so the new key sorts the bindings in the order they were made,
moves the primary key onto it, and indexes ``info_item_id`` to replace the
composite key's leading column. The downgrade refuses once a pair has two rows.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from ulid import ULID

_MIGRATION = next(
    (Path(__file__).parent.parent.parent / "alembic" / "versions").glob(
        "*_info_item_sources_binding_id.py"
    )
)
_ITEM = "01J0000000000000000000I392"
_SOURCES = ("01J0000000000000000000A392", "01J0000000000000000000B392")


def _load_migration():
    spec = importlib.util.spec_from_file_location("_info_item_sources_binding_id", _MIGRATION)
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


async def _primary_key(test_engine) -> str:
    async with test_engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                    " WHERE conrelid = 'information.info_item_sources'::regclass"
                    "   AND contype = 'p'"
                )
            )
        ).scalar_one()


async def _seed_parents(conn) -> None:
    await conn.execute(
        text("INSERT INTO information.info_items (info_item_id, name) VALUES (:i, 'm392')"),
        {"i": _ITEM},
    )
    for n, source_id in enumerate(_SOURCES):
        await conn.execute(
            text(
                "INSERT INTO information.info_sources (info_source_id, url, source_specs)"
                " VALUES (:s, :u, '[]'::jsonb)"
            ),
            {"s": source_id, "u": f"https://example.com/m392-{n}"},
        )


async def _cleanup(test_engine) -> None:
    async with test_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM information.info_items WHERE info_item_id = :i"), {"i": _ITEM}
        )
        await conn.execute(
            text("DELETE FROM information.info_sources WHERE info_source_id = ANY(:s)"),
            {"s": list(_SOURCES)},
        )


@pytest.mark.asyncio
async def test_head_keys_bindings_by_id(test_engine):
    assert await _primary_key(test_engine) == "PRIMARY KEY (id)"


@pytest.mark.asyncio
async def test_head_indexes_bindings_by_item(test_engine):
    async with test_engine.connect() as conn:
        defs = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'information'"
                    "   AND tablename = 'info_item_sources'"
                )
            )
        ).scalars()
        assert any(d.endswith("USING btree (info_item_id)") for d in defs)


@pytest.mark.asyncio
async def test_upgrade_backfills_an_id_minted_from_created_at(test_engine):
    first = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    second = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await _run(test_engine, "downgrade")
    try:
        assert await _primary_key(test_engine) == "PRIMARY KEY (info_item_id, info_source_id)"
        async with test_engine.begin() as conn:
            await _seed_parents(conn)
            for source_id, created_at in zip(_SOURCES, (second, first), strict=True):
                await conn.execute(
                    text(
                        "INSERT INTO information.info_item_sources"
                        " (info_item_id, info_source_id, created_at, deactivated_at)"
                        " VALUES (:i, :s, :c, :d)"
                    ),
                    {
                        "i": _ITEM,
                        "s": source_id,
                        "c": created_at,
                        "d": second if created_at == first else None,
                    },
                )
    finally:
        await _run(test_engine, "upgrade")
    try:
        assert await _primary_key(test_engine) == "PRIMARY KEY (id)"
        async with test_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, info_source_id, created_at FROM information.info_item_sources"
                        " WHERE info_item_id = :i ORDER BY id"
                    ),
                    {"i": _ITEM},
                )
            ).all()
        assert [r.info_source_id for r in rows] == [_SOURCES[1], _SOURCES[0]]
        for row in rows:
            assert ULID.from_str(row.id).datetime == row.created_at
    finally:
        await _cleanup(test_engine)


@pytest.mark.asyncio
async def test_downgrade_refuses_two_tenures_of_one_pair(test_engine):
    async with test_engine.begin() as conn:
        await _seed_parents(conn)
        for deactivated_at in (datetime(2026, 5, 2, tzinfo=UTC), None):
            await conn.execute(
                text(
                    "INSERT INTO information.info_item_sources"
                    " (id, info_item_id, info_source_id, deactivated_at)"
                    " VALUES (:id, :i, :s, :d)"
                ),
                {"id": str(ULID()), "i": _ITEM, "s": _SOURCES[0], "d": deactivated_at},
            )
    try:
        with pytest.raises(Exception, match="more than one tenure"):
            await _run(test_engine, "downgrade")
        assert await _primary_key(test_engine) == "PRIMARY KEY (id)"
    finally:
        await _cleanup(test_engine)
