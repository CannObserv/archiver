"""Tests for the update_rep_spec core tool (archiver#83, tiers 1+2).

The tiered mutability contract (see
docs/plans/2026-07-20-83-rep-spec-document-editing-adr.md):

- tier 1: ``name`` is always mutable.
- tier 2: ``document`` is mutable only while the RepSpec is a *draft* —
  zero ``info_item_rep_specs`` rows, active or deactivated.
- tier 3: an assigned RepSpec is frozen; clone + migrate instead (#95).

``provider`` is frozen in all tiers.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, RepSpec
from src.core.tools.assign_rep_spec import assign_rep_spec, lock_rep_specs
from src.core.tools.create_rep_spec import create_rep_spec
from src.core.tools.update_rep_spec import (
    InvalidRepSpecError,
    RepSpecNotDraftError,
    RepSpecNotFoundError,
    update_rep_spec,
)


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.date}.html",
        "required_fields": ["info_item.slug", "source_revision.date"],
        "object_options": {"storage_class": "STANDARD"},
    }


async def _draft(session, *, name: str = "draft-spec") -> RepSpec:
    """A RepSpec with no assignment rows."""
    spec = await create_rep_spec(session, provider="gcs", name=name, document=_gcs_doc())
    await session.flush()
    return spec


async def _assign(session, spec: RepSpec, *, deactivated: bool = False) -> InfoItemRepSpec:
    """Attach an assignment row to *spec*, optionally already deactivated."""
    item = InfoItem(name=f"item-for-{spec.name}", rep_fields={})
    session.add(item)
    await session.flush()
    row = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime.now(UTC),
        deactivated_at=datetime.now(UTC) if deactivated else None,
    )
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Tier 1 — name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updates_name_on_a_draft(session):
    spec = await _draft(session)
    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, name="renamed")
    await session.commit()

    fetched = await session.get(RepSpec, updated.rep_spec_id)
    assert fetched.name == "renamed"


@pytest.mark.asyncio
async def test_updates_name_even_when_assigned(session):
    """Tier 1: ``name`` is a label with no replication semantics."""
    spec = await _draft(session)
    await _assign(session, spec)

    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, name="renamed-anyway")
    await session.commit()

    assert (await session.get(RepSpec, updated.rep_spec_id)).name == "renamed-anyway"


@pytest.mark.asyncio
async def test_name_only_update_leaves_document_untouched(session):
    spec = await _draft(session)
    original = dict(spec.document)

    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, name="renamed")
    await session.commit()

    assert updated.document == original


# ---------------------------------------------------------------------------
# Tier 2 — document, drafts only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replaces_document_on_a_draft(session):
    spec = await _draft(session)
    new_doc = _gcs_doc() | {"path_template": "corrected/{info_item.slug}.html"}

    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=new_doc)
    await session.commit()

    fetched = await session.get(RepSpec, updated.rep_spec_id)
    assert fetched.document["path_template"] == "corrected/{info_item.slug}.html"


@pytest.mark.asyncio
async def test_document_update_is_replace_not_merge(session):
    """Whole-document replacement: dropped keys are actually dropped."""
    spec = await _draft(session)
    new_doc = _gcs_doc()
    del new_doc["object_options"]

    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=new_doc)
    await session.commit()

    assert "object_options" not in updated.document


@pytest.mark.asyncio
async def test_document_update_rejected_when_active_assignment_exists(session):
    spec = await _draft(session)
    await _assign(session, spec)

    with pytest.raises(RepSpecNotDraftError):
        await update_rep_spec(
            session,
            rep_spec_id=spec.rep_spec_id,
            document=_gcs_doc() | {"path_template": "nope/{info_item.slug}"},
        )


@pytest.mark.asyncio
async def test_document_update_rejected_when_only_deactivated_assignment_exists(session):
    """The draft gate counts *all* rows — a deactivated assignment still ran."""
    spec = await _draft(session)
    await _assign(session, spec, deactivated=True)

    with pytest.raises(RepSpecNotDraftError) as exc:
        await update_rep_spec(
            session,
            rep_spec_id=spec.rep_spec_id,
            document=_gcs_doc() | {"path_template": "nope/{info_item.slug}"},
        )
    assert exc.value.assignment_count == 1


@pytest.mark.asyncio
async def test_not_draft_error_reports_assignment_count(session):
    spec = await _draft(session)
    await _assign(session, spec)
    await _assign(session, spec, deactivated=True)

    with pytest.raises(RepSpecNotDraftError) as exc:
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=_gcs_doc())
    assert exc.value.assignment_count == 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_document_missing_envelope_field(session):
    spec = await _draft(session)
    bad = _gcs_doc()
    del bad["path_template"]

    with pytest.raises(InvalidRepSpecError) as exc:
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=bad)
    assert any("path_template" in e["message"] for e in exc.value.errors)


@pytest.mark.asyncio
async def test_rejects_document_failing_provider_sub_schema(session):
    spec = await _draft(session)
    bad = _gcs_doc()
    bad["object_options"] = {"storage_class": "BANANA"}

    with pytest.raises(InvalidRepSpecError) as exc:
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=bad)
    assert any(e["path"].startswith("/object_options") for e in exc.value.errors)


@pytest.mark.asyncio
async def test_rejects_provider_change(session):
    """Provider is frozen in all tiers, drafts included."""
    spec = await _draft(session)
    swapped = {
        "provider": "gdrive",
        "credentials_alias": "gdrive-prod",
        "path_template": "{info_item.slug}",
        "required_fields": ["info_item.slug"],
        "object_options": {},
    }

    with pytest.raises(InvalidRepSpecError) as exc:
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=swapped)
    assert any(e["path"] == "/provider" for e in exc.value.errors)


@pytest.mark.asyncio
async def test_invalid_document_does_not_mutate_the_row(session):
    spec = await _draft(session)
    original = dict(spec.document)
    bad = _gcs_doc()
    del bad["path_template"]

    with pytest.raises(InvalidRepSpecError):
        await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, document=bad)

    assert (await session.get(RepSpec, spec.rep_spec_id)).document == original


# ---------------------------------------------------------------------------
# Lookup + no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_not_found_for_unknown_id(session):
    with pytest.raises(RepSpecNotFoundError):
        await update_rep_spec(session, rep_spec_id=ULID(), name="x")


@pytest.mark.asyncio
async def test_omitting_both_fields_is_a_no_op(session):
    spec = await _draft(session, name="unchanged")
    original = dict(spec.document)

    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id)
    await session.commit()

    assert updated.name == "unchanged"
    assert updated.document == original


# ---------------------------------------------------------------------------
# updated_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updated_at_is_null_until_first_edit(session):
    spec = await _draft(session)
    assert spec.updated_at is None


@pytest.mark.asyncio
async def test_updated_at_is_stamped_on_edit(session):
    spec = await _draft(session)
    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id, name="renamed")
    await session.commit()

    assert updated.updated_at is not None
    assert updated.updated_at >= updated.created_at


@pytest.mark.asyncio
async def test_updated_at_not_stamped_on_no_op(session):
    """A call that changes nothing should not claim an edit happened."""
    spec = await _draft(session)
    updated = await update_rep_spec(session, rep_spec_id=spec.rep_spec_id)
    await session.commit()

    assert updated.updated_at is None


# ---------------------------------------------------------------------------
# Concurrency — the draft gate must not be bypassable (CR round 1, finding 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_document_edit_and_assignment_serialize_on_the_rep_spec_row(
    test_engine, committed_rows
):
    """A concurrent assignment must not slip past the draft gate.

    Without row locking both writers read a stale view under READ COMMITTED: the
    editor counts zero assignments, the assigner sees a draft, and both commit —
    leaving a rewritten document on an assigned RepSpec, which is exactly the
    audit-trail corruption the tiered contract exists to prevent. Both paths take
    ``FOR UPDATE`` on the RepSpec row, so the second writer waits.

    Uses real independent transactions (not the SAVEPOINT-scoped ``session``
    fixture) because row locks are only observable across separate connections.
    """
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async with make_session() as setup:
        spec = await create_rep_spec(setup, provider="gcs", name="race-spec", document=_gcs_doc())
        item = InfoItem(
            name="race-item",
            rep_fields={"info_item": {"slug": "s"}, "source_revision": {"date": "2026-07-20"}},
        )
        setup.add(item)
        await setup.commit()
        spec_id, item_id = spec.rep_spec_id, item.info_item_id
        committed_rows += [(RepSpec, spec_id), (InfoItem, item_id)]

    async with make_session() as editor, make_session() as assigner:
        # Editor grabs the row lock and holds it — no commit yet.
        await update_rep_spec(
            editor,
            rep_spec_id=spec_id,
            document=_gcs_doc() | {"path_template": "edited/{info_item.slug}"},
        )

        task = asyncio.create_task(
            assign_rep_spec(assigner, info_item_id=item_id, rep_spec_id=spec_id)
        )
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "assignment proceeded while the document edit held the row lock"

        await editor.commit()
        assignment = await asyncio.wait_for(task, timeout=10.0)
        await assigner.commit()
        committed_rows.append((InfoItemRepSpec, assignment.id))


@pytest.mark.asyncio
async def test_lock_rep_specs_blocks_a_concurrent_document_edit(test_engine, committed_rows):
    """The atomic-create path must take the same lock as assign_rep_spec.

    ``POST /info-items`` inserts InfoItemRepSpec rows directly rather than going
    through ``assign_rep_spec``, so it needs ``lock_rep_specs`` to close the same
    race (CR round 2, finding 8).
    """
    make_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async with make_session() as setup:
        spec = await create_rep_spec(setup, provider="gcs", name="lock-helper", document=_gcs_doc())
        await setup.commit()
        spec_id = spec.rep_spec_id
        committed_rows.append((RepSpec, spec_id))

    async with make_session() as editor, make_session() as creator:
        await update_rep_spec(
            editor,
            rep_spec_id=spec_id,
            document=_gcs_doc() | {"path_template": "edited/{info_item.slug}"},
        )

        task = asyncio.create_task(lock_rep_specs(creator, [str(spec_id)]))
        done, _ = await asyncio.wait({task}, timeout=1.0)
        assert not done, "atomic-create lookup proceeded while the edit held the row lock"

        await editor.commit()
        locked = await asyncio.wait_for(task, timeout=10.0)
        assert str(spec_id) in locked
        await creator.rollback()


@pytest.mark.asyncio
async def test_lock_rep_specs_returns_empty_for_no_ids(session):
    assert await lock_rep_specs(session, []) == {}


@pytest.mark.asyncio
async def test_lock_rep_specs_omits_unknown_ids(session):
    """Callers detect 404s by absence, so unknown IDs must simply not appear."""
    spec = await _draft(session, name="known")
    await session.commit()
    found = await lock_rep_specs(session, [str(spec.rep_spec_id), "01J0000000000000000000000Z"])
    assert list(found) == [str(spec.rep_spec_id)]
