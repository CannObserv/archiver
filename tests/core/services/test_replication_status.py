"""The dashboard's read of replication state (archiver#171).

`public_url` acquires an automated writer in #170, so the assignment views need
to say *why* a URL is what it is — or why there is none. That answer is the
**latest occasion** per assignment, and the awkward part is that a refusal is an
occasion too: #169 persists `state="skipped"` rows precisely so that a
replication which silently did not happen stops rendering as "not replicated
yet" forever.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services.replication_issuance import (
    SKIP_BLOB_EXPIRED,
    STATE_REQUESTED,
    STATE_SKIPPED,
)
from src.core.services.replication_status import latest_commands_by_assignment
from src.core.services.replication_writeback import STATE_COMPLETE

ISSUED_AT = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)


@pytest.fixture
async def assignment(session) -> InfoItemRepSpec:
    source = InfoSource(url="https://example.com/status", source_specs=[])
    item = InfoItem(name="status-item", rep_fields={})
    spec = RepSpec(provider="gcs", name="status-spec", schema_version=1, document={})
    session.add_all([source, item, spec])
    await session.flush()
    row = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + "c" * 64,
        captured_at=ISSUED_AT,
    )
    session.add_all([row, revision])
    await session.flush()
    row._revision = revision  # carried for the helper below
    return row


def _command(assignment, *, command_id: str, state: str, issued_at: datetime, **kw):
    revision = assignment._revision
    return ReplicationCommand(
        command_id=command_id,
        info_item_rep_spec_id=assignment.id,
        source_revision_id=revision.source_revision_id,
        info_source_id=revision.info_source_id,
        provider="gcs",
        credentials_alias="alias",
        media_type="text/html",
        state=state,
        issued_at=issued_at,
        **kw,
    )


@pytest.mark.asyncio
async def test_returns_the_newest_occasion_per_assignment(session, assignment):
    session.add(_command(assignment, command_id="old", state=STATE_COMPLETE, issued_at=ISSUED_AT))
    session.add(
        _command(
            assignment,
            command_id="new",
            state=STATE_REQUESTED,
            issued_at=ISSUED_AT + timedelta(hours=1),
        )
    )
    await session.flush()

    latest = await latest_commands_by_assignment(session, [assignment.id])

    assert latest[assignment.id].command_id == "new"


@pytest.mark.asyncio
async def test_a_skip_is_an_occasion_and_wins_when_it_is_newest(session, assignment):
    """The reason the skip rows exist: invisible refusals read as 'pending'."""
    session.add(_command(assignment, command_id="done", state=STATE_COMPLETE, issued_at=ISSUED_AT))
    session.add(
        _command(
            assignment,
            command_id="skip",
            state=STATE_SKIPPED,
            reason=SKIP_BLOB_EXPIRED,
            issued_at=ISSUED_AT + timedelta(hours=1),
        )
    )
    await session.flush()

    latest = await latest_commands_by_assignment(session, [assignment.id])

    assert latest[assignment.id].command_id == "skip"
    assert latest[assignment.id].reason == SKIP_BLOB_EXPIRED


@pytest.mark.asyncio
async def test_ties_break_on_command_id(session, assignment):
    """Two occasions minted in the same instant still order deterministically —
    the same ULID-monotonicity argument `_is_newest_occasion` leans on."""
    session.add(_command(assignment, command_id="aaa", state=STATE_REQUESTED, issued_at=ISSUED_AT))
    session.add(_command(assignment, command_id="bbb", state=STATE_REQUESTED, issued_at=ISSUED_AT))
    await session.flush()

    latest = await latest_commands_by_assignment(session, [assignment.id])

    assert latest[assignment.id].command_id == "bbb"


@pytest.mark.asyncio
async def test_an_assignment_with_no_occasion_is_absent_not_none(session, assignment):
    latest = await latest_commands_by_assignment(session, [assignment.id])

    assert latest == {}


@pytest.mark.asyncio
async def test_no_ids_issues_no_query(session):
    assert await latest_commands_by_assignment(session, []) == {}
