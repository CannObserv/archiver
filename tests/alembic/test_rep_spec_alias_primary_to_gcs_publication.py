"""The ``primary`` → ``gcs-publication`` RepSpec alias rewrite (archiver#276).

Production's one RepSpec is assigned, so #83 froze its ``document`` and
``PATCH /rep-specs/{id}`` refuses the edit. The rewrite is a one-off data
migration instead, safe because Replicator binds both names to the same bucket
and prefix since the publication cutover (replicator#114 plan step 4).

What needs pinning is its scope: only a ``gcs`` RepSpec's ``credentials_alias``
equal to ``primary`` moves, every other key of the document stays byte-equal,
and the edit is stamped in ``updated_at`` like any other document edit.

Drives the migration module's ``upgrade()`` under a real ``MigrationContext``
rather than re-typing its SQL, as the archiver#161 backfill test does.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import RepSpec

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "70f32f641751_rep_spec_alias_primary_to_gcs_publication.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_alias_primary_rewrite", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def session_factory(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def clean_rep_specs(test_engine):
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.rep_specs CASCADE"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.rep_specs CASCADE"))


async def _run_upgrade(test_engine) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            module.upgrade()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


def _document(provider: str, alias: str) -> dict:
    return {
        "provider": provider,
        "credentials_alias": alias,
        "path_template": "orgs/{org.title_slug}/{source_revision.id}.{source_revision.ext}",
        "required_fields": ["org.title"],
        "object_options": {"storage_class": "STANDARD"},
    }


async def _add(session_factory, provider: str, alias: str) -> RepSpec:
    async with session_factory() as s:
        spec = RepSpec(
            provider=provider,
            name=f"{provider}/{alias}",
            schema_version=1,
            document=_document(provider, alias),
        )
        s.add(spec)
        await s.commit()
        return spec


async def _reload(session_factory, spec: RepSpec) -> RepSpec:
    async with session_factory() as s:
        return (
            await s.execute(select(RepSpec).where(RepSpec.rep_spec_id == spec.rep_spec_id))
        ).scalar_one()


@pytest.mark.asyncio
async def test_a_gcs_rep_spec_on_primary_moves_to_gcs_publication(session_factory, test_engine):
    spec = await _add(session_factory, "gcs", "primary")

    await _run_upgrade(test_engine)

    row = await _reload(session_factory, spec)
    assert row.document == _document("gcs", "gcs-publication")
    assert row.updated_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "alias"),
    [("gcs", "gcs-publication"), ("gcs", "gcs-archive"), ("ia", "primary")],
)
async def test_every_other_rep_spec_is_untouched(session_factory, test_engine, provider, alias):
    """Only ``gcs`` bound ``primary``; an ``ia`` document naming it is some other
    fault, and rewriting it would give it a gcs alias under an ia provider."""
    spec = await _add(session_factory, provider, alias)

    await _run_upgrade(test_engine)

    row = await _reload(session_factory, spec)
    assert row.document == _document(provider, alias)
    assert row.updated_at is None


@pytest.mark.asyncio
async def test_a_rerun_matches_nothing(session_factory, test_engine):
    spec = await _add(session_factory, "gcs", "primary")
    await _run_upgrade(test_engine)
    first = (await _reload(session_factory, spec)).updated_at

    await _run_upgrade(test_engine)

    assert (await _reload(session_factory, spec)).updated_at == first
