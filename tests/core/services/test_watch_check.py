"""Check-now via ``info.watch-check`` (archiver#370, epic #359 A11).

Covers:
1. The F4 switch: unset/falsy → off; truthy → on (D6)
2. The no-answer timeout: default 15 min, malformed/non-positive → default (D5)
3. The state ladder, each rung against fixtures, in its order (D2)
4. Issuance: a command row and an outbox row in one transaction, requested_at
   stamped at the outbox write; refused while the switch is off (D6)
5. One open command per item: refused while pending, allowed after each
   terminal rung (D4)
6. The rejection write: recorded, idempotent first-write-wins, unknown id (D3)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from co_core.pure.models.changes import CheckRejectedEvent, WatchCheckCommand
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, WatchStatus
from src.core.models import WatchCheckCommand as CommandRow
from src.core.services import watch_check
from src.core.services.watch_check import (
    DEFAULT_TIMEOUT,
    ENABLED_ENV,
    TIMEOUT_ENV,
    WATCH_CHECK_TOPIC,
    CheckAlreadyOpen,
    CheckNowDisabled,
    check_enabled,
    check_state,
    check_timeout,
    latest_check,
    record_rejection,
    request_check,
)

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
ON = {ENABLED_ENV: "1"}


def _command(**overrides) -> CommandRow:
    values = dict(
        command_id=str(ULID()), info_item_id=ULID(), requested_at=T0, rejected_reason=None
    )
    values.update(overrides)
    return CommandRow(**values)


def _status(**overrides) -> WatchStatus:
    values = dict(
        info_item_id=ULID(),
        applied_generation=1,
        applied_active=True,
        health="ok",
        last_full_fetch_at=None,
        health_reason=None,
        health_status_code=None,
        occurred_at=T0,
    )
    values.update(overrides)
    return WatchStatus(**values)


async def _item(session: AsyncSession) -> InfoItem:
    item = InfoItem(name="Check me")
    session.add(item)
    await session.commit()
    return item


def _rejection(command_id: str, *, reason: str = "fetch_open", **overrides) -> CheckRejectedEvent:
    values = dict(
        occurred_at=T0 + timedelta(seconds=30),
        event_id=str(ULID()),
        info_item_id=str(ULID()),
        info_source_id=None,
        command_id=command_id,
        reason=reason,
    )
    values.update(overrides)
    return CheckRejectedEvent(**values)


class TestSwitch:
    @pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
    def test_truthy_is_on(self, value):
        assert check_enabled({ENABLED_ENV: value}) is True

    @pytest.mark.parametrize("environ", [{}, {ENABLED_ENV: ""}, {ENABLED_ENV: "0"}])
    def test_unset_or_falsy_is_off(self, environ):
        assert check_enabled(environ) is False


class TestTimeout:
    def test_default_is_fifteen_minutes(self):
        assert DEFAULT_TIMEOUT == timedelta(minutes=15)
        assert check_timeout({}) == DEFAULT_TIMEOUT

    def test_seconds_override(self):
        assert check_timeout({TIMEOUT_ENV: "120"}) == timedelta(seconds=120)

    @pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "nan", "inf"])
    def test_malformed_or_non_positive_is_the_default(self, raw):
        assert check_timeout({TIMEOUT_ENV: raw}) == DEFAULT_TIMEOUT


class TestLadder:
    """D2's rungs, first match wins: rejected → done → no answer → pending."""

    def test_rejected_wins_over_everything(self):
        command = _command(rejected_reason="paused", rejected_at=T0)
        status = _status(last_full_fetch_at=T0 + timedelta(minutes=1))
        state = check_state(command, status, now=T0 + timedelta(hours=1))
        assert state.kind == "rejected"
        assert state.reason == "paused"

    def test_an_unknown_rejection_token_is_kept_verbatim(self):
        state = check_state(
            _command(rejected_reason="brand_new_token"), None, now=T0 + timedelta(seconds=5)
        )
        assert (state.kind, state.reason) == ("rejected", "brand_new_token")

    def test_done_when_a_full_fetch_postdates_the_request(self):
        status = _status(last_full_fetch_at=T0 + timedelta(seconds=40), health="ok")
        state = check_state(_command(), status, now=T0 + timedelta(minutes=1))
        assert state.kind == "done"
        assert state.health == "ok"
        assert state.health_ok is True
        assert state.completed_at == T0 + timedelta(seconds=40)

    def test_done_with_a_failed_extraction_carries_the_error(self):
        """A 200 whose extraction then failed: done, plus the error and its reason."""
        status = _status(
            last_full_fetch_at=T0 + timedelta(seconds=40),
            health="error",
            health_reason="processing_failed",
        )
        state = check_state(_command(), status, now=T0 + timedelta(minutes=1))
        assert state.kind == "done"
        assert state.health_ok is False
        assert state.health_reason == "processing_failed"

    def test_done_even_past_the_timeout(self):
        """No answer is not a verdict (D5): a later completion still flips it."""
        status = _status(last_full_fetch_at=T0 + timedelta(minutes=40))
        state = check_state(_command(), status, now=T0 + timedelta(hours=1))
        assert state.kind == "done"

    def test_a_fetch_at_exactly_requested_at_is_not_done(self):
        status = _status(last_full_fetch_at=T0)
        state = check_state(_command(), status, now=T0 + timedelta(seconds=5))
        assert state.kind == "pending"

    def test_an_older_fetch_is_not_done(self):
        status = _status(last_full_fetch_at=T0 - timedelta(hours=1))
        state = check_state(_command(), status, now=T0 + timedelta(seconds=5))
        assert state.kind == "pending"

    def test_no_answer_past_the_timeout(self):
        state = check_state(_command(), None, now=T0 + DEFAULT_TIMEOUT + timedelta(seconds=1))
        assert state.kind == "no_answer"

    def test_pending_at_exactly_the_timeout(self):
        state = check_state(_command(), None, now=T0 + DEFAULT_TIMEOUT)
        assert state.kind == "pending"

    def test_the_timeout_is_a_parameter(self):
        state = check_state(
            _command(), None, now=T0 + timedelta(seconds=61), timeout=timedelta(seconds=60)
        )
        assert state.kind == "no_answer"

    def test_pending_otherwise(self):
        state = check_state(_command(), _status(), now=T0 + timedelta(seconds=5))
        assert state.kind == "pending"
        assert state.open is True

    @pytest.mark.parametrize(
        ("command", "status", "now"),
        [
            (_command(rejected_reason="paused"), None, T0),
            (_command(), _status(last_full_fetch_at=T0 + timedelta(seconds=1)), T0),
            (_command(), None, T0 + timedelta(hours=1)),
        ],
        ids=["rejected", "done", "no_answer"],
    )
    def test_only_pending_is_open(self, command, status, now):
        assert check_state(command, status, now=now).open is False


class TestRequest:
    async def test_writes_a_command_and_its_outbox_row(self, session: AsyncSession):
        item = await _item(session)

        row = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()

        stored = await session.get(CommandRow, row.command_id)
        assert stored.info_item_id == item.info_item_id
        outbox = (await session.execute(select(ChangesOutboxRow))).scalars().all()
        assert [o.topic for o in outbox] == [WATCH_CHECK_TOPIC] == ["info.watch-check"]
        payload = WatchCheckCommand.model_validate(outbox[0].payload)
        assert payload.command_id == row.command_id
        assert payload.info_item_id == str(item.info_item_id)
        # Stamped at the outbox write: one instant for the row and both wire stamps.
        assert payload.requested_at == payload.occurred_at == stored.requested_at

    async def test_refused_while_the_switch_is_off(self, session: AsyncSession):
        item = await _item(session)

        with pytest.raises(CheckNowDisabled):
            await request_check(session, item.info_item_id, requested_by=None, environ={})
        await session.commit()

        assert (await session.execute(select(func.count(CommandRow.command_id)))).scalar() == 0
        assert (await session.execute(select(func.count(ChangesOutboxRow.id)))).scalar() == 0

    async def test_refused_while_one_is_pending(self, session: AsyncSession):
        item = await _item(session)
        await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()

        with pytest.raises(CheckAlreadyOpen):
            await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.rollback()

        assert (await session.execute(select(func.count(ChangesOutboxRow.id)))).scalar() == 1

    async def test_a_new_click_after_a_rejection_mints_a_fresh_command(self, session: AsyncSession):
        item = await _item(session)
        first = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()
        await record_rejection(session, _rejection(first.command_id))
        await session.commit()

        second = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()

        assert second.command_id != first.command_id
        assert second.requested_at >= first.requested_at
        assert (await session.execute(select(func.count(ChangesOutboxRow.id)))).scalar() == 2

    async def test_a_new_click_after_no_answer_is_allowed(self, session: AsyncSession):
        item = await _item(session)
        session.add(
            CommandRow(
                command_id=str(ULID()),
                info_item_id=item.info_item_id,
                requested_at=datetime.now(UTC) - DEFAULT_TIMEOUT - timedelta(minutes=1),
            )
        )
        await session.commit()

        await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()

        assert (await session.execute(select(func.count(CommandRow.command_id)))).scalar() == 2

    async def test_a_new_click_after_done_is_allowed(self, session: AsyncSession):
        item = await _item(session)
        first = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        session.add(
            WatchStatus(
                info_item_id=item.info_item_id,
                applied_generation=1,
                applied_active=True,
                health="ok",
                last_full_fetch_at=first.requested_at + timedelta(seconds=10),
                occurred_at=first.requested_at + timedelta(seconds=10),
            )
        )
        await session.commit()

        await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        await session.commit()

        assert (await session.execute(select(func.count(CommandRow.command_id)))).scalar() == 2

    async def test_latest_check_reads_the_newest_command(self, session: AsyncSession):
        item = await _item(session)
        older = str(ULID())
        newer = str(ULID())
        session.add_all(
            [
                CommandRow(
                    command_id=newer,
                    info_item_id=item.info_item_id,
                    requested_at=T0 + timedelta(minutes=5),
                ),
                CommandRow(command_id=older, info_item_id=item.info_item_id, requested_at=T0),
            ]
        )
        await session.commit()

        latest = await latest_check(session, item.info_item_id)
        assert latest.command_id == newer
        assert await latest_check(session, ULID()) is None


class TestRecordRejection:
    async def test_records_the_reason_and_the_fact_time(self, session: AsyncSession):
        item = await _item(session)
        row = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        command_id = row.command_id
        await session.commit()

        fact = _rejection(command_id, reason="domain_suspended")
        assert await record_rejection(session, fact) == "recorded"
        await session.commit()
        session.expire_all()

        stored = await session.get(CommandRow, command_id)
        assert stored.rejected_reason == "domain_suspended"
        assert stored.rejected_at == fact.occurred_at

    async def test_a_second_rejection_is_a_no_op(self, session: AsyncSession):
        """A redelivered command can mint a second event_id; the first write wins."""
        item = await _item(session)
        row = await request_check(session, item.info_item_id, requested_by=None, environ=ON)
        command_id = row.command_id
        await session.commit()
        await record_rejection(session, _rejection(command_id, reason="fetch_open"))
        await session.commit()

        again = _rejection(command_id, reason="paused", occurred_at=T0 + timedelta(minutes=5))
        assert await record_rejection(session, again) == "duplicate"
        await session.commit()
        session.expire_all()

        stored = await session.get(CommandRow, command_id)
        assert stored.rejected_reason == "fetch_open"

    async def test_an_unknown_command_id_is_reported(self, session: AsyncSession):
        assert await record_rejection(session, _rejection(str(ULID()))) == "unknown_command"


def test_the_topic_is_co_cores():
    assert watch_check.WATCH_CHECK_TOPIC == "info.watch-check"
