"""Viewport capture via ``content.capture`` (archiver#380 slice A).

Covers:
1. The switch: unset/falsy → off; truthy → on
2. Issuance: a command row and an outbox row in one transaction, the fixed
   default profile, resolved values only; refused while off
3. One open command per source: refused while requested, allowed after each
   terminal state and for another source
4. ``capture_stored``: closes the command with what was stored; the first
   success is kept (C1); a success outranks a failure or an abandon
5. ``capture_failed``: terminal closes, non-terminal records and stays open,
   a failure never overrides a success, an older fact never overrides a newer
6. Unknown ``command_id`` → ``UnknownCommandError`` (ack-and-drop upstream)
7. The reaper: abandons silent commands past the horizon
8. Keeping it: ``capture_stored`` issues ``content.persist`` (slice B)
9. Slice C: the source's policy shapes every command; a new revision of an
   opted-in source issues one; the reaper re-issues a silent one, capped
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.adapters.bus.streams import CONTENT_CAPTURE, CONTENT_PERSIST
from co_core.pure.models.changes import (
    CaptureFailedEvent,
    CaptureStoredEvent,
    ContentCaptureCommand,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.capture_policy import CapturePolicy
from src.core.models import (
    AppUser,
    CaptureCommand,
    ChangesOutboxRow,
    InfoSource,
    PersistCommand,
    SourceRevision,
)
from src.core.services import capture, persist_issuance
from src.core.services.capture import (
    DEFAULT_FULL_PAGE,
    DEFAULT_VIEWPORT,
    ENABLED_ENV,
    MAX_CAPTURE_REISSUES,
    REASON_NO_FACT,
    CaptureAlreadyOpen,
    CaptureDisabled,
    CapturePolicyInvalid,
    apply_capture_failed,
    apply_capture_stored,
    capture_enabled,
    capture_for_revision,
    latest_capture,
    reap_open_captures,
    request_capture,
    set_capture_policy,
)
from src.core.services.replication_writeback import UnknownCommandError

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
ON = {ENABLED_ENV: "1"}
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


async def _source(session: AsyncSession, url: str = "https://example.com/page") -> InfoSource:
    source = InfoSource(url=url, source_specs=[])
    session.add(source)
    await session.flush()
    return source


async def _issued(session: AsyncSession, source: InfoSource) -> CaptureCommand:
    command = await request_capture(session, source.info_source_id, requested_by=None, environ=ON)
    await session.flush()
    return command


def _stored(command: CaptureCommand, *, digest: str = DIGEST_A, at: datetime = T0, **overrides):
    values = dict(
        occurred_at=at,
        command_id=command.command_id,
        url=command.url,
        info_source_id=str(command.info_source_id),
        content_fingerprint=digest,
        blob_uri=f"gs://co-gcs-blobs/blobs/{digest}.bin",
        media_type="image/png",
        size_bytes=4096,
        image_width=1280,
        image_height=5120,
        final_url=command.url + "?landed",
        captured_at=at - timedelta(seconds=2),
        blob_expires_at=at + timedelta(days=7),
    )
    values.update(overrides)
    return CaptureStoredEvent(**values)


def _failed(command: CaptureCommand, *, at: datetime = T0, **overrides) -> CaptureFailedEvent:
    values = dict(
        occurred_at=at,
        command_id=command.command_id,
        url=command.url,
        info_source_id=str(command.info_source_id),
        reason="http_status",
        terminal=True,
        status_code=404,
        detail="navigation answered 404",
    )
    values.update(overrides)
    return CaptureFailedEvent(**values)


async def _outbox(session: AsyncSession) -> list[ChangesOutboxRow]:
    return list(
        (
            await session.execute(
                select(ChangesOutboxRow).where(ChangesOutboxRow.topic == CONTENT_CAPTURE)
            )
        )
        .scalars()
        .all()
    )


# --- 1. the switch ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, False), ("", False), ("0", False), ("no", False), ("1", True), (" TRUE ", True)],
)
def test_the_switch(raw, expected):
    environ = {} if raw is None else {ENABLED_ENV: raw}
    assert capture_enabled(environ) is expected


# --- 2. issuance ---


@pytest.mark.asyncio
async def test_off_writes_nothing(session):
    source = await _source(session)
    with pytest.raises(CaptureDisabled):
        await request_capture(session, source.info_source_id, requested_by=None, environ={})
    await session.flush()
    assert await _outbox(session) == []
    count = await session.execute(select(func.count()).select_from(CaptureCommand))
    assert count.scalar_one() == 0


@pytest.mark.asyncio
async def test_a_request_writes_the_row_and_the_command_together(session):
    source = await _source(session)
    user = AppUser(external_id="ext-380-svc", email="op@example.com")
    session.add(user)
    await session.flush()

    command = await request_capture(
        session, source.info_source_id, requested_by=user.id, environ=ON
    )
    await session.flush()

    assert command.state == "requested"
    assert command.requested_by == user.id
    assert command.url == source.url
    assert (command.viewport_width, command.viewport_height) == DEFAULT_VIEWPORT
    assert command.full_page is DEFAULT_FULL_PAGE
    assert command.wait is None

    [row] = await _outbox(session)
    wire = ContentCaptureCommand.model_validate(row.payload)
    assert wire.command_id == command.command_id
    assert wire.url == source.url
    assert wire.info_source_id == str(source.info_source_id)
    assert (wire.viewport.width, wire.viewport.height) == DEFAULT_VIEWPORT
    assert wire.full_page is DEFAULT_FULL_PAGE
    assert wire.wait is None
    # Resolved values only (C4): the command carries no headers or credential.
    assert set(row.payload) == {
        "schema_version",
        "event_type",
        "occurred_at",
        "command_id",
        "url",
        "info_source_id",
        "viewport",
        "full_page",
        "wait",
    }


def test_the_default_profile():
    """The one profile slice A sends; slice C's policy replaces it per source."""
    assert DEFAULT_VIEWPORT == (1280, 800)
    assert DEFAULT_FULL_PAGE is True


@pytest.mark.asyncio
async def test_each_request_mints_a_fresh_command_id(session):
    source = await _source(session)
    first = await _issued(session, source)
    await apply_capture_failed(session, _failed(first))
    second = await _issued(session, source)
    assert first.command_id != second.command_id
    assert ULID.from_str(second.command_id)


@pytest.mark.asyncio
async def test_an_unknown_source_is_refused(session):
    with pytest.raises(LookupError):
        await request_capture(session, ULID(), requested_by=None, environ=ON)


# --- 3. one open command per source ---


@pytest.mark.asyncio
async def test_a_second_request_while_one_is_open_is_refused(session):
    source = await _source(session)
    await _issued(session, source)
    with pytest.raises(CaptureAlreadyOpen):
        await request_capture(session, source.info_source_id, requested_by=None, environ=ON)
    await session.flush()
    assert len(await _outbox(session)) == 1


@pytest.mark.asyncio
async def test_another_source_is_not_blocked(session):
    await _issued(session, await _source(session))
    await _issued(session, await _source(session, "https://example.com/other"))
    assert len(await _outbox(session)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["stored", "failed", "abandoned"])
async def test_a_closed_command_does_not_block(session, closing):
    source = await _source(session)
    first = await _issued(session, source)
    if closing == "stored":
        await apply_capture_stored(session, _stored(first))
    elif closing == "failed":
        await apply_capture_failed(session, _failed(first))
    else:
        first.issued_at = datetime.now(UTC) - timedelta(hours=2)
        await reap_open_captures(session, horizon=timedelta(hours=1))
    await session.flush()

    second = await _issued(session, source)
    assert second.command_id != first.command_id
    latest = await latest_capture(session, source.info_source_id)
    assert latest.command_id == second.command_id


@pytest.mark.asyncio
async def test_latest_capture_of_a_source_never_captured(session):
    source = await _source(session)
    assert await latest_capture(session, source.info_source_id) is None


# --- 4. capture_stored ---


@pytest.mark.asyncio
async def test_a_success_closes_the_command_with_what_was_stored(session):
    source = await _source(session)
    command = await _issued(session, source)
    fact = _stored(command)

    await apply_capture_stored(session, fact)

    assert command.state == "stored"
    assert command.terminal is True
    assert command.closed_at is not None
    assert command.last_fact_at == fact.occurred_at
    assert command.content_fingerprint == DIGEST_A
    assert command.blob_uri == fact.blob_uri
    assert command.media_type == "image/png"
    assert command.size_bytes == 4096
    assert (command.image_width, command.image_height) == (1280, 5120)
    assert command.final_url == fact.final_url
    assert command.captured_at == fact.captured_at
    assert command.blob_expires_at == fact.blob_expires_at


@pytest.mark.asyncio
async def test_the_first_success_is_kept(session):
    """C1: a redelivery past Replicator's dedupe window renders again, usually
    under another digest. Either is a true capture; the first stays."""
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_stored(session, _stored(command))

    await apply_capture_stored(
        session, _stored(command, digest=DIGEST_B, at=T0 + timedelta(minutes=10))
    )

    assert command.content_fingerprint == DIGEST_A
    assert command.last_fact_at == T0


@pytest.mark.asyncio
@pytest.mark.parametrize("prior", ["failed", "abandoned"])
async def test_a_success_outranks_a_failure_or_an_abandon(session, prior):
    """A stored image exists once any fact says so."""
    source = await _source(session)
    command = await _issued(session, source)
    if prior == "failed":
        await apply_capture_failed(session, _failed(command, at=T0 + timedelta(minutes=1)))
    else:
        command.issued_at = datetime.now(UTC) - timedelta(hours=2)
        await reap_open_captures(session, horizon=timedelta(hours=1))

    await apply_capture_stored(session, _stored(command))

    assert command.state == "stored"
    assert command.reason is None
    assert command.detail is None
    assert command.status_code is None
    assert command.content_fingerprint == DIGEST_A


# --- 5. capture_failed ---


@pytest.mark.asyncio
async def test_a_terminal_failure_closes_the_command(session):
    source = await _source(session)
    command = await _issued(session, source)

    await apply_capture_failed(session, _failed(command))

    assert command.state == "failed"
    assert command.terminal is True
    assert command.reason == "http_status"
    assert command.status_code == 404
    assert command.detail == "navigation answered 404"
    assert command.closed_at is not None
    assert command.last_fact_at == T0


@pytest.mark.asyncio
async def test_an_unknown_reason_is_stored_verbatim(session):
    """C2: the vocabulary is producer-owned; an unknown token is opaque."""
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_failed(
        session, _failed(command, reason="a_token_from_the_future", status_code=None)
    )
    assert command.state == "failed"
    assert command.reason == "a_token_from_the_future"


@pytest.mark.asyncio
async def test_a_non_terminal_failure_records_and_stays_open(session):
    source = await _source(session)
    command = await _issued(session, source)

    await apply_capture_failed(session, _failed(command, terminal=False, reason="still_trying"))

    assert command.state == "requested"
    assert command.closed_at is None
    assert command.terminal is False
    assert command.reason == "still_trying"


@pytest.mark.asyncio
async def test_a_failure_never_overrides_a_success(session):
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_stored(session, _stored(command))

    await apply_capture_failed(session, _failed(command, at=T0 + timedelta(minutes=5)))

    assert command.state == "stored"
    assert command.reason is None
    assert command.content_fingerprint == DIGEST_A


@pytest.mark.asyncio
async def test_an_older_failure_does_not_override_a_newer_one(session):
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_failed(
        session, _failed(command, at=T0 + timedelta(minutes=5), reason="wait_timeout")
    )

    await apply_capture_failed(session, _failed(command, at=T0, reason="http_status"))

    assert command.reason == "wait_timeout"
    assert command.last_fact_at == T0 + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_a_non_terminal_failure_does_not_reopen_or_rewrite_a_closed_command(session):
    """CR 4: once abandoned, a still-trying fact leaves the reaper's verdict whole."""
    source = await _source(session)
    command = await _issued(session, source)
    command.issued_at = datetime.now(UTC) - timedelta(hours=2)
    await reap_open_captures(session, horizon=timedelta(hours=1))

    await apply_capture_failed(session, _failed(command, terminal=False, reason="still_trying"))

    assert command.state == "abandoned"
    assert command.reason == REASON_NO_FACT
    assert command.terminal is not False


@pytest.mark.asyncio
async def test_a_terminal_failure_closes_an_abandoned_command_as_failed(session):
    """Replicator's verdict is more specific than the reaper's guess at silence."""
    source = await _source(session)
    command = await _issued(session, source)
    command.issued_at = datetime.now(UTC) - timedelta(hours=2)
    await reap_open_captures(session, horizon=timedelta(hours=1))

    await apply_capture_failed(session, _failed(command, reason="wait_timeout", status_code=None))

    assert command.state == "failed"
    assert command.reason == "wait_timeout"
    assert command.terminal is True


# --- 6. unknown command ---


@pytest.mark.asyncio
async def test_an_unknown_command_raises(session):
    source = await _source(session)
    ghost = CaptureCommand(
        command_id=str(ULID()), info_source_id=source.info_source_id, url=source.url
    )
    with pytest.raises(UnknownCommandError):
        await apply_capture_stored(session, _stored(ghost))
    with pytest.raises(UnknownCommandError):
        await apply_capture_failed(session, _failed(ghost))


# --- 7. the reaper ---


@pytest.mark.asyncio
async def test_the_reaper_abandons_silent_commands_past_the_horizon(session):
    old_source = await _source(session)
    fresh_source = await _source(session, "https://example.com/fresh")
    old = await _issued(session, old_source)
    fresh = await _issued(session, fresh_source)
    old.issued_at = datetime.now(UTC) - timedelta(hours=2)
    await session.flush()

    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)

    assert result.abandoned == 1
    assert old.state == "abandoned"
    assert old.reason == REASON_NO_FACT
    assert old.closed_at is not None
    assert fresh.state == "requested"


@pytest.mark.asyncio
async def test_the_reaper_leaves_closed_commands_alone(session):
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_stored(session, _stored(command))
    command.issued_at = datetime.now(UTC) - timedelta(hours=2)
    await session.flush()

    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)
    assert (result.abandoned, result.reissued) == (0, 0)
    assert command.state == "stored"


def test_the_default_horizon():
    assert capture.DEFAULT_REAP_HORIZON == timedelta(hours=1)


# --- 8. keeping it: capture_stored issues content.persist (slice B, C3) ---


@pytest.fixture
def persist_on(monkeypatch):
    monkeypatch.setenv(persist_issuance.ISSUANCE_ENV, "1")


async def _persists(session) -> list[PersistCommand]:
    return list((await session.execute(select(PersistCommand))).scalars().all())


@pytest.mark.asyncio
async def test_a_stored_capture_is_persisted_in_the_same_transaction(session, persist_on):
    source = await _source(session)
    command = await _issued(session, source)

    await apply_capture_stored(session, _stored(command))
    await session.flush()

    [persist] = await _persists(session)
    assert persist.capture_command_id == command.command_id
    assert persist.content_fingerprint == DIGEST_A
    assert persist.blob_uri == f"gs://co-gcs-blobs/blobs/{DIGEST_A}.bin"
    assert persist.media_type == "image/png"
    [row] = (
        (
            await session.execute(
                select(ChangesOutboxRow).where(ChangesOutboxRow.topic == CONTENT_PERSIST)
            )
        )
        .scalars()
        .all()
    )
    assert row.payload["command_id"] == persist.command_id


@pytest.mark.asyncio
async def test_a_redelivered_success_issues_no_second_persist(session, persist_on):
    source = await _source(session)
    command = await _issued(session, source)
    await apply_capture_stored(session, _stored(command))
    await session.flush()
    persist = (await _persists(session))[0]
    persist.state = "persisted"
    persist.closed_at = datetime.now(UTC)
    await session.flush()

    await apply_capture_stored(
        session, _stored(command, digest=DIGEST_B, at=T0 + timedelta(minutes=10))
    )
    await session.flush()

    assert len(await _persists(session)) == 1


@pytest.mark.asyncio
async def test_no_persist_while_persist_issuance_is_off(session, monkeypatch):
    monkeypatch.delenv(persist_issuance.ISSUANCE_ENV, raising=False)
    source = await _source(session)
    command = await _issued(session, source)

    await apply_capture_stored(session, _stored(command))
    await session.flush()

    assert command.state == "stored"
    assert await _persists(session) == []


# --- 9. slice C: the policy, the revision trigger, the capped re-issue ---

POLICY = {
    "viewport": {"width": 390, "height": 844},
    "full_page": False,
    "wait": {"kind": "selector", "selector": "#main", "seconds": None},
    "on_revision": True,
}
SENT_WAIT = {"kind": "selector", "selector": "#main", "seconds": None}


async def _revision(session: AsyncSession, source: InfoSource) -> SourceRevision:
    revision = SourceRevision(
        info_source_id=source.info_source_id,
        content_fingerprint="sha256:" + str(ULID()).lower().ljust(64, "0")[:64],
        captured_at=T0,
    )
    session.add(revision)
    await session.flush()
    return revision


@pytest.mark.asyncio
async def test_a_request_sends_the_sources_policy(session):
    source = await _source(session)
    source.capture_policy = POLICY
    await session.flush()

    command = await _issued(session, source)

    [row] = await _outbox(session)
    sent = ContentCaptureCommand.model_validate(row.payload)
    assert (sent.viewport.width, sent.viewport.height, sent.full_page) == (390, 844, False)
    assert sent.wait.model_dump() == SENT_WAIT
    assert (command.viewport_width, command.viewport_height) == (390, 844)
    assert command.full_page is False
    assert command.wait == SENT_WAIT
    assert (command.attempt, command.reissue_of, command.source_revision_id) == (1, None, None)


@pytest.mark.asyncio
async def test_a_request_with_no_policy_sends_the_default(session):
    source = await _source(session)
    command = await _issued(session, source)
    assert (command.viewport_width, command.viewport_height) == DEFAULT_VIEWPORT
    assert command.full_page is DEFAULT_FULL_PAGE
    assert command.wait is None


@pytest.mark.asyncio
async def test_an_invalid_stored_policy_refuses_the_request_and_writes_nothing(session):
    """Validated on write, so only a later-tightened schema reaches here: never send it."""
    source = await _source(session)
    source.capture_policy = {"viewport": {"width": 0, "height": 800}}
    await session.flush()

    with pytest.raises(CapturePolicyInvalid):
        await request_capture(session, source.info_source_id, requested_by=None, environ=ON)
    assert await _outbox(session) == []


@pytest.mark.asyncio
async def test_a_new_revision_of_an_opted_in_source_is_captured(session):
    source = await _source(session)
    source.capture_policy = POLICY
    revision = await _revision(session, source)

    command = await capture_for_revision(session, revision, environ=ON)

    assert command is not None
    assert command.source_revision_id == revision.source_revision_id
    assert command.requested_by is None
    assert (command.viewport_width, command.full_page, command.wait) == (390, False, SENT_WAIT)
    [row] = await _outbox(session)
    assert row.payload["command_id"] == command.command_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [None, {**POLICY, "on_revision": False}],
    ids=["no-policy", "on-demand-only"],
)
async def test_a_source_not_opted_in_is_not_captured_on_revision(session, policy):
    source = await _source(session)
    source.capture_policy = policy
    revision = await _revision(session, source)

    assert await capture_for_revision(session, revision, environ=ON) is None
    assert await _outbox(session) == []


@pytest.mark.asyncio
async def test_no_revision_capture_while_the_switch_is_off(session):
    source = await _source(session)
    source.capture_policy = POLICY
    revision = await _revision(session, source)

    assert await capture_for_revision(session, revision, environ={}) is None
    assert await _outbox(session) == []


@pytest.mark.asyncio
async def test_a_revision_while_a_capture_is_open_issues_nothing(session):
    """One open command per source: the open one renders the live page anyway."""
    source = await _source(session)
    source.capture_policy = POLICY
    await _issued(session, source)
    revision = await _revision(session, source)

    assert await capture_for_revision(session, revision, environ=ON) is None
    assert len(await _outbox(session)) == 1


@pytest.mark.asyncio
async def test_an_invalid_stored_policy_skips_the_revision_capture(session):
    """The bus consumer must not dead-letter a revision over a capture setting."""
    source = await _source(session)
    source.capture_policy = {"on_revision": True, "viewport": {"width": 0, "height": 1}}
    revision = await _revision(session, source)

    assert await capture_for_revision(session, revision, environ=ON) is None
    assert await _outbox(session) == []


async def _silent(session: AsyncSession, command: CaptureCommand) -> None:
    command.issued_at = datetime.now(UTC) - timedelta(hours=2)
    await session.flush()


@pytest.mark.asyncio
async def test_the_reaper_reissues_a_silent_command_with_what_it_sent(session):
    """C2: silence is "still trying" or "lost"; re-issue under a fresh command_id."""
    source = await _source(session)
    source.capture_policy = POLICY
    revision = await _revision(session, source)
    user = AppUser(external_id="ext-380c", email="c@example.com")
    session.add(user)
    await session.flush()
    first = await request_capture(session, source.info_source_id, requested_by=user.id, environ=ON)
    first.source_revision_id = revision.source_revision_id
    await _silent(session, first)
    # The policy changing after the send does not change what the re-issue asks.
    source.capture_policy = {**POLICY, "full_page": True}

    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)

    assert (result.abandoned, result.reissued) == (1, 1)
    assert first.state == "abandoned"
    second = await latest_capture(session, source.info_source_id)
    assert second.command_id != first.command_id
    assert (second.reissue_of, second.attempt, second.state) == (first.command_id, 2, "requested")
    assert second.source_revision_id == revision.source_revision_id
    assert second.requested_by == user.id
    assert (second.url, second.viewport_width, second.viewport_height) == (first.url, 390, 844)
    assert (second.full_page, second.wait) == (False, SENT_WAIT)
    rows = await _outbox(session)
    assert [r.payload["command_id"] for r in rows] == [first.command_id, second.command_id]
    assert ContentCaptureCommand.model_validate(rows[1].payload).full_page is False


@pytest.mark.asyncio
async def test_the_reissue_is_capped(session):
    source = await _source(session)
    command = await _issued(session, source)
    for _ in range(MAX_CAPTURE_REISSUES):
        await _silent(session, command)
        result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)
        assert result.reissued == 1
        command = await latest_capture(session, source.info_source_id)

    assert command.attempt == 1 + MAX_CAPTURE_REISSUES
    await _silent(session, command)
    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)

    assert (result.abandoned, result.reissued) == (1, 0)
    assert (await latest_capture(session, source.info_source_id)).state == "abandoned"
    assert len(await _outbox(session)) == 1 + MAX_CAPTURE_REISSUES


@pytest.mark.asyncio
async def test_no_reissue_while_the_switch_is_off(session):
    source = await _source(session)
    command = await _issued(session, source)
    await _silent(session, command)

    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ={})

    assert (result.abandoned, result.reissued) == (1, 0)
    assert command.state == "abandoned"
    assert len(await _outbox(session)) == 1


@pytest.mark.asyncio
async def test_no_reissue_when_a_newer_command_exists(session):
    """The source's newest command already answers for it."""
    source = await _source(session)
    old = await _issued(session, source)
    await _silent(session, old)
    # Bypass the one-open rule to stand in for a race: a newer command exists.
    newer = CaptureCommand(
        command_id=str(ULID()),
        info_source_id=source.info_source_id,
        url=source.url,
        viewport_width=1280,
        viewport_height=800,
        full_page=True,
        state="stored",
        issued_at=datetime.now(UTC),
    )
    session.add(newer)
    await session.flush()

    result = await reap_open_captures(session, horizon=timedelta(hours=1), environ=ON)

    assert (result.abandoned, result.reissued) == (1, 0)
    assert len(await _outbox(session)) == 1


def test_the_reissue_cap():
    assert MAX_CAPTURE_REISSUES == 2


@pytest.mark.asyncio
async def test_set_capture_policy_stores_the_normalized_document(session):
    source = await _source(session)
    stored = await set_capture_policy(
        session, source.info_source_id, CapturePolicy.model_validate({"on_revision": True})
    )
    assert stored.capture_policy == {
        "viewport": {"width": 1280, "height": 800},
        "full_page": True,
        "wait": None,
        "on_revision": True,
    }


@pytest.mark.asyncio
async def test_set_capture_policy_none_clears_it(session):
    source = await _source(session)
    source.capture_policy = POLICY
    stored = await set_capture_policy(session, source.info_source_id, None)
    assert stored.capture_policy is None


@pytest.mark.asyncio
async def test_set_capture_policy_on_an_unknown_source_raises(session):
    with pytest.raises(LookupError):
        await set_capture_policy(session, ULID(), None)
