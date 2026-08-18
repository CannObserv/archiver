"""Closing a replication command from ``content.artifacts`` (archiver#170).

``public_url`` is the point of the whole exercise — a column with no automated
writer until this lands. The properties here are the issuer contract's:

- MUST-4: correlation is idempotent, and one command legitimately yields *many*
  facts. T4's no-op row re-emits a success for an artifact already written, so a
  repeat is expected traffic rather than an anomaly.
- MUST-6: branch on ``terminal`` — a non-terminal failure means Replicator is
  still retrying and the command stays open.
- R3: ``public_url`` is not stable across occasions, so the assignment row holds
  the *newest* one and an older occasion's fact must not overwrite it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.core.models import (
    InfoItem,
    InfoItemRepSpec,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services.replication_issuance import STATE_REQUESTED
from src.core.services.replication_writeback import (
    STATE_ABANDONED,
    STATE_COMPLETE,
    STATE_FAILED,
    UnknownCommandError,
    apply_failure,
    apply_success,
    reap_open_commands,
)

PUBLIC_URL = "https://storage.googleapis.com/co-archive/archive/wa-lcb/x.html"
OCCURRED_AT = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.fixture
async def assignment(session) -> InfoItemRepSpec:
    source = InfoSource(url="https://example.com/writeback", source_specs=[])
    item = InfoItem(name="writeback-item", rep_fields={})
    spec = RepSpec(provider="gcs", name="writeback-spec", schema_version=1, document={})
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
        captured_at=datetime.now(UTC),
    )
    session.add_all([row, revision])
    await session.flush()
    row.test_revision = revision  # carried for the helpers below
    return row


async def _command(session, assignment, *, command_id: str, issued_at: datetime | None = None):
    revision = assignment.test_revision
    command = ReplicationCommand(
        command_id=command_id,
        info_item_rep_spec_id=assignment.id,
        source_revision_id=revision.source_revision_id,
        info_source_id=revision.info_source_id,
        provider="gcs",
        credentials_alias="alias",
        destination="archive/wa-lcb/x.html",
        media_type="text/html",
        blob_uri="file:///blobs/x.bin",
        state=STATE_REQUESTED,
        issued_at=issued_at or datetime.now(UTC),
    )
    session.add(command)
    await session.flush()
    return command


# --- replication_complete ---


@pytest.mark.asyncio
async def test_success_writes_public_url_to_the_assignment_and_closes_the_command(
    session, assignment
):
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_success(
        session,
        command_id="cmd-1",
        public_url=PUBLIC_URL,
        occurred_at=OCCURRED_AT,
    )

    assert assignment.public_url == PUBLIC_URL
    assert command.state == STATE_COMPLETE
    assert command.public_url == PUBLIC_URL
    assert command.closed_at is not None


@pytest.mark.asyncio
async def test_repeated_success_is_idempotent(session, assignment):
    """T4's no-op row re-emits the same fact for an artifact already written."""
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)
    first_closed_at = command.closed_at
    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)

    assert assignment.public_url == PUBLIC_URL
    assert command.closed_at == first_closed_at


@pytest.mark.asyncio
async def test_unknown_command_id_is_reported_not_written(session, assignment):
    """A fact about a command the registry does not hold — ack-and-drop, matching
    the unknown-info_source_id posture on content.revisions."""
    with pytest.raises(UnknownCommandError):
        await apply_success(
            session, command_id="never-issued", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT
        )


@pytest.mark.asyncio
async def test_an_older_occasion_does_not_overwrite_a_newer_public_url(session, assignment):
    """R3: each occasion yields its own URL; the assignment holds the newest."""
    older = await _command(
        session,
        assignment,
        command_id="cmd-old",
        issued_at=datetime.now(UTC) - timedelta(hours=2),
    )
    await _command(session, assignment, command_id="cmd-new")

    await apply_success(
        session, command_id="cmd-new", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT
    )
    await apply_success(
        session,
        command_id="cmd-old",
        public_url="https://storage.googleapis.com/co-archive/stale.html",
        occurred_at=OCCURRED_AT,
    )

    assert assignment.public_url == PUBLIC_URL
    # The older occasion still records what happened to it.
    assert older.public_url == "https://storage.googleapis.com/co-archive/stale.html"
    assert older.state == STATE_COMPLETE


@pytest.mark.asyncio
async def test_success_for_a_deactivated_assignment_still_records(session, assignment):
    """The row is the historical record; a deactivation does not unmake the write."""
    await _command(session, assignment, command_id="cmd-1")
    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()

    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)

    assert assignment.public_url == PUBLIC_URL


# --- replication_failed ---


@pytest.mark.asyncio
async def test_terminal_failure_closes_the_command(session, assignment):
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="blob_expired",
        terminal=True,
        attempts=1,
        detail="past the horizon",
        occurred_at=OCCURRED_AT,
    )

    assert command.state == STATE_FAILED
    assert command.reason == "blob_expired"
    assert command.terminal is True
    assert command.closed_at is not None


@pytest.mark.asyncio
async def test_non_terminal_failure_leaves_the_command_open(session, assignment):
    """MUST-6: False means Replicator is still retrying — do not close it."""
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="provider_unavailable",
        terminal=False,
        attempts=2,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    assert command.state == STATE_REQUESTED
    assert command.terminal is False
    assert command.attempts == 2
    assert command.closed_at is None


@pytest.mark.asyncio
async def test_an_unknown_reason_token_is_stored_verbatim(session, assignment):
    """The vocabulary is producer-owned; branching on it here would make every
    new token a code change."""
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="invalid_source",
        terminal=True,
        attempts=None,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    assert command.reason == "invalid_source"


@pytest.mark.asyncio
async def test_failure_does_not_touch_public_url(session, assignment):
    """A failed occasion says nothing about the artifact an earlier one wrote."""
    await _command(session, assignment, command_id="cmd-1")
    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)
    await _command(session, assignment, command_id="cmd-2")

    await apply_failure(
        session,
        command_id="cmd-2",
        reason="destination_conflict",
        terminal=True,
        attempts=None,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    assert assignment.public_url == PUBLIC_URL


@pytest.mark.asyncio
async def test_a_success_after_a_non_terminal_failure_still_completes(session, assignment):
    command = await _command(session, assignment, command_id="cmd-1")
    await apply_failure(
        session,
        command_id="cmd-1",
        reason="provider_unavailable",
        terminal=False,
        attempts=1,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)

    assert command.state == STATE_COMPLETE
    assert command.closed_at is not None


# --- the reaper (MUST-6) ---


@pytest.mark.asyncio
async def test_reaper_abandons_a_command_open_past_the_horizon(session, assignment):
    """Replicator does not guarantee every command succeeds or is closed: a
    provider 5xx retries unbounded and publishes no fact at all meanwhile."""
    stale = await _command(
        session,
        assignment,
        command_id="cmd-stale",
        issued_at=datetime.now(UTC) - timedelta(hours=9),
    )

    reaped = await reap_open_commands(session, horizon=timedelta(hours=6))

    assert reaped == 1
    assert stale.state == STATE_ABANDONED
    assert stale.closed_at is not None
    assert stale.reason is not None


@pytest.mark.asyncio
async def test_reaper_leaves_a_recent_command_alone(session, assignment):
    recent = await _command(session, assignment, command_id="cmd-recent")

    assert await reap_open_commands(session, horizon=timedelta(hours=6)) == 0

    assert recent.state == STATE_REQUESTED


@pytest.mark.asyncio
async def test_reaper_does_not_reissue(session, assignment):
    """No auto-reissue: this capability writes into permanent stores, one of
    which cannot be deleted at all. Re-issue stays an operator act."""
    await _command(
        session,
        assignment,
        command_id="cmd-stale",
        issued_at=datetime.now(UTC) - timedelta(hours=9),
    )

    await reap_open_commands(session, horizon=timedelta(hours=6))

    rows = (await session.execute(select(ReplicationCommand))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_reaper_ignores_closed_and_skipped_commands(session, assignment):
    done = await _command(
        session,
        assignment,
        command_id="cmd-done",
        issued_at=datetime.now(UTC) - timedelta(hours=9),
    )
    done.state = STATE_COMPLETE
    done.closed_at = datetime.now(UTC)
    await session.flush()

    assert await reap_open_commands(session, horizon=timedelta(hours=6)) == 0


# --- ordering and state monotonicity (CR round 3) ---


@pytest.mark.asyncio
async def test_a_later_skip_row_does_not_suppress_the_writeback(session, assignment):
    """A skipped occasion produced no artifact, so it has no claim on the slot (CR #19).

    Skips are written for every active assignment whenever a revision arrives
    with no blob, so one of those while a replication is in flight would
    otherwise suppress that artifact's URL permanently — silently, with the
    command row holding a public_url the assignment never shows.
    """
    await _command(
        session,
        assignment,
        command_id="cmd-real",
        issued_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    skip = await _command(session, assignment, command_id="cmd-skip")
    skip.state = "skipped"
    skip.closed_at = datetime.now(UTC)
    await session.flush()

    await apply_success(
        session, command_id="cmd-real", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT
    )

    assert assignment.public_url == PUBLIC_URL


@pytest.mark.asyncio
async def test_a_stale_failure_does_not_flip_a_completed_command(session, assignment):
    """content.artifacts is at-least-once and keyed per emission, so an
    out-of-order redelivery is expected traffic (CR #20)."""
    command = await _command(session, assignment, command_id="cmd-1")
    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="destination_conflict",
        terminal=True,
        attempts=1,
        detail=None,
        occurred_at=OCCURRED_AT - timedelta(hours=1),
    )

    assert command.state == STATE_COMPLETE
    assert command.public_url == PUBLIC_URL


@pytest.mark.asyncio
async def test_a_stale_non_terminal_failure_does_not_downgrade_terminal(session, assignment):
    """state='failed' with terminal=False contradicts itself, and the reaper
    cannot correct it — it only looks at open commands (CR #21)."""
    command = await _command(session, assignment, command_id="cmd-1")
    await apply_failure(
        session,
        command_id="cmd-1",
        reason="blob_expired",
        terminal=True,
        attempts=3,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="provider_unavailable",
        terminal=False,
        attempts=1,
        detail=None,
        occurred_at=OCCURRED_AT - timedelta(hours=1),
    )

    assert command.state == STATE_FAILED
    assert command.terminal is True
    assert command.reason == "blob_expired"


@pytest.mark.asyncio
async def test_a_newer_fact_still_applies(session, assignment):
    """The guard is on staleness, not on having seen a fact before."""
    command = await _command(session, assignment, command_id="cmd-1")
    await apply_failure(
        session,
        command_id="cmd-1",
        reason="provider_unavailable",
        terminal=False,
        attempts=1,
        detail=None,
        occurred_at=OCCURRED_AT,
    )

    await apply_failure(
        session,
        command_id="cmd-1",
        reason="blob_expired",
        terminal=True,
        attempts=2,
        detail=None,
        occurred_at=OCCURRED_AT + timedelta(minutes=5),
    )

    assert command.state == STATE_FAILED
    assert command.reason == "blob_expired"
    assert command.last_fact_at == OCCURRED_AT + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_a_redelivery_of_the_same_emission_still_applies(session, assignment):
    """Equal occurred_at is the same emission, not a stale one — T4 re-emits."""
    command = await _command(session, assignment, command_id="cmd-1")

    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)
    await apply_success(session, command_id="cmd-1", public_url=PUBLIC_URL, occurred_at=OCCURRED_AT)

    assert command.state == STATE_COMPLETE
    assert assignment.public_url == PUBLIC_URL
