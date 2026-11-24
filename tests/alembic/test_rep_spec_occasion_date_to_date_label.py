"""The ``{source_revision.date}`` → ``{source_revision.date_label}`` rewrite (archiver#523).

The occasion key was renamed to the shared storage vocabulary's name for the
same ``YYYY-MM-DD`` string, with no alias kept, so a stored template naming the
old key would no longer render. The migration rewrites it in every RepSpec's
``path_template``, draft or assigned. For an assigned (frozen) document, this is
a recorded #83 exception (operator, 2026-11-17), safe for the same reason
``70f32f641751``'s was: the rendered destination is byte-identical.

What needs pinning is its scope:
- only the exact ``{source_revision.date}`` token moves, so ``date_segment``,
  ``datetime_time_segment`` and an already-renamed ``date_label`` survive;
- only ``path_template`` is touched, and every other key stays byte-equal;
- the edit is stamped in ``updated_at``;
- downgrade restores the original document (the round trip is lossless).

Drives the migration module under a real ``MigrationContext`` rather than
re-typing its SQL, as ``test_rep_spec_alias_primary_to_gcs_publication`` does.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.replication.destination import RenderOccasion, render_destination

_MIGRATION = (
    Path(__file__).parent.parent.parent
    / "alembic"
    / "versions"
    / "e4897ee850d9_rep_spec_occasion_date_to_date_label.py"
)

_OCCASION = RenderOccasion(
    source_revision_id="01JZZZZZZZZZZZZZZZZZZZZZZZ",
    content_fingerprint="sha256:" + "ab" * 32,
    captured_at=datetime(2026, 8, 17, 23, 30, 5, tzinfo=UTC),
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("_occasion_date_label_rewrite", _MIGRATION)
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
        await conn.execute(text("TRUNCATE TABLE information.info_items CASCADE"))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE information.rep_specs CASCADE"))
        await conn.execute(text("TRUNCATE TABLE information.info_items CASCADE"))


async def _run(test_engine, direction: str) -> None:
    module = _load_migration()

    def _apply(sync_conn):
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            getattr(module, direction)()

    async with test_engine.begin() as conn:
        await conn.run_sync(_apply)


def _document(path_template: str) -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-publication",
        "path_template": path_template,
        "required_fields": ["info_item.slug"],
        # Not path_template: the migration must leave this key's text alone.
        "object_options": {"storage_class": "STANDARD", "x_note": "{source_revision.date}"},
    }


async def _add(session_factory, path_template: str, *, assigned: bool) -> RepSpec:
    async with session_factory() as s:
        spec = RepSpec(
            provider="gcs",
            name=path_template,
            schema_version=1,
            document=_document(path_template),
        )
        s.add(spec)
        if assigned:
            item = InfoItem(name=f"item {path_template}", rep_fields={"info_item": {"slug": "s"}})
            s.add(item)
            await s.flush()
            s.add(
                InfoItemRepSpec(
                    info_item_id=item.info_item_id,
                    rep_spec_id=spec.rep_spec_id,
                    activated_at=datetime.now(UTC),
                )
            )
        await s.commit()
        return spec


async def _reload(session_factory, spec: RepSpec) -> RepSpec:
    async with session_factory() as s:
        return (
            await s.execute(select(RepSpec).where(RepSpec.rep_spec_id == spec.rep_spec_id))
        ).scalar_one()


OLD = "archive/{info_item.slug}/{source_revision.date}/{source_revision.id}.html"
NEW = "archive/{info_item.slug}/{source_revision.date_label}/{source_revision.id}.html"


@pytest.mark.asyncio
@pytest.mark.parametrize("assigned", [False, True], ids=["draft", "assigned"])
async def test_the_old_key_is_rewritten_and_the_round_trip_restores_it(
    session_factory, test_engine, assigned
):
    spec = await _add(session_factory, OLD, assigned=assigned)

    await _run(test_engine, "upgrade")

    row = await _reload(session_factory, spec)
    assert row.document == _document(NEW)
    assert row.updated_at is not None
    # The rewrite moves no destination: the new key renders the bytes the old one did.
    rendered = render_destination(
        row.document["path_template"],
        rep_fields={"info_item": {"slug": "s"}},
        occasion=_OCCASION,
        org=None,
    )
    assert rendered == "archive/s/2026-08-17/01JZZZZZZZZZZZZZZZZZZZZZZZ.html"

    await _run(test_engine, "downgrade")

    assert (await _reload(session_factory, spec)).document == _document(OLD)


@pytest.mark.asyncio
async def test_every_occurrence_in_one_template_is_rewritten(session_factory, test_engine):
    spec = await _add(
        session_factory,
        "{source_revision.date}/{source_revision.date}-{source_revision.id}",
        assigned=False,
    )

    await _run(test_engine, "upgrade")

    assert (await _reload(session_factory, spec)).document["path_template"] == (
        "{source_revision.date_label}/{source_revision.date_label}-{source_revision.id}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path_template",
    [
        "{source_revision.year}/{source_revision.date_segment}/{source_revision.id}",
        "{source_revision.datetime_time_segment}-{source_revision.id}.{source_revision.ext}",
        "{source_revision.date_label}/{source_revision.id}",
        "{info_item.date}/{source_revision.id}",
        "source_revision.date/{source_revision.id}",
    ],
    ids=["date_segment", "datetime_time_segment", "date_label", "bag_date", "unbraced"],
)
async def test_anything_but_the_exact_token_is_untouched(
    session_factory, test_engine, path_template
):
    """A plain ``source_revision.date`` substring would also match ``date_segment``."""
    spec = await _add(session_factory, path_template, assigned=True)

    await _run(test_engine, "upgrade")

    row = await _reload(session_factory, spec)
    assert row.document == _document(path_template)
    assert row.updated_at is None


@pytest.mark.asyncio
async def test_downgrade_leaves_documents_without_the_new_key_alone(session_factory, test_engine):
    spec = await _add(
        session_factory, "{source_revision.date_segment}/{source_revision.id}", assigned=False
    )

    await _run(test_engine, "downgrade")

    row = await _reload(session_factory, spec)
    assert row.document == _document("{source_revision.date_segment}/{source_revision.id}")
    assert row.updated_at is None


@pytest.mark.asyncio
async def test_a_rerun_matches_nothing(session_factory, test_engine):
    spec = await _add(session_factory, OLD, assigned=True)
    await _run(test_engine, "upgrade")
    first = (await _reload(session_factory, spec)).updated_at

    await _run(test_engine, "upgrade")

    assert (await _reload(session_factory, spec)).updated_at == first
