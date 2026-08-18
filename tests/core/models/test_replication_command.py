"""ReplicationCommand column contracts (archiver#169)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services.replication_issuance import STATE_REQUESTED


async def _assignment_and_revision(session) -> tuple[InfoItemRepSpec, SourceRevision]:
    source = InfoSource(url="https://example.com/state-check", source_specs=[])
    item = InfoItem(name="state-check-item", rep_fields={})
    spec = RepSpec(provider="gcs", name="state-check-spec", schema_version=1, document={})
    session.add_all([source, item, spec])
    await session.flush()
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "f" * 64,
        captured_at=datetime.now(UTC),
    )
    session.add_all([assignment, revision])
    await session.flush()
    return assignment, revision


def _command(assignment, revision, state: str) -> ReplicationCommand:
    return ReplicationCommand(
        command_id=str(ULID()),
        info_item_rep_spec_id=assignment.id,
        source_revision_id=revision.source_revision_id,
        info_source_id=revision.info_source_id,
        provider="gcs",
        credentials_alias="alias",
        media_type="text/html",
        state=state,
    )


@pytest.mark.asyncio
async def test_unknown_state_is_rejected_by_the_database(session):
    """The reaper's partial index hard-codes state = 'requested' (CR #13).

    Without a constraint, a renamed or mistyped state is written happily and the
    index simply stops matching — the reaper then reports an empty queue, which
    is the silence MUST-6's reaper exists to break.
    """
    assignment, revision = await _assignment_and_revision(session)
    session.add(_command(assignment, revision, "in_flight"))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_the_declared_states_are_accepted(session):
    assignment, revision = await _assignment_and_revision(session)
    for state in ("requested", "complete", "failed", "abandoned", "skipped"):
        session.add(_command(assignment, revision, state))
    await session.flush()


@pytest.mark.asyncio
async def test_issuance_state_constant_is_one_the_database_allows(session):
    """The service's constants and the constraint cannot drift apart silently."""
    assignment, revision = await _assignment_and_revision(session)
    session.add(_command(assignment, revision, STATE_REQUESTED))
    await session.flush()
