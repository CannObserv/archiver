"""What the Bus triage screen tells the operator about each action (archiver#271).

Every outcome the core functions can return gets its own message, at a level
that says whether anything changed. Collapsing them into success / failure is
the failure mode the brief names: ``refused`` and ``rejected`` leave a row for
different reasons, and the remedy differs.
"""

from datetime import UTC, datetime

import pytest
from co_core.pure.adapters.bus.dead_letter import DeadLetterProvenance

from src.core.changes.dlq_triage import (
    DeadLetter,
    DiscardInterruptedError,
    DiscardResult,
    ReprocessInterruptedError,
    ReprocessOutcome,
    ReprocessResult,
)
from src.core.changes.outbox_triage import DiscardOutcome, RearmOutcome, RearmResult
from src.dashboard import bus_triage
from src.dashboard.bus_triage import (
    discard_confirm,
    dlq_discard_flash,
    dlq_discard_interrupted_flash,
    duplicate_frames,
    outbox_discard_flash,
    rearm_flash,
    reprocess_flash,
    reprocess_interrupted_flash,
)

ROW = "01HZZ000000000000000000001"
ENTRY = "1727179200000-0"
DLQ = "content.revisions.dlq"


def _entry(entry_id: str = ENTRY, *, group: str | None, source_id: str | None = None) -> DeadLetter:
    return DeadLetter(
        entry_id=entry_id,
        dead_lettered_at=datetime(2026, 9, 24, tzinfo=UTC),
        fields={},
        event_type=None,
        decodes=False,
        decode_error=None,
        provenance=DeadLetterProvenance(
            source_id=source_id, group=group, consumer=None, reason=None
        ),
        parked_as=None,
        owned=group == "archiver.revisions",
    )


# --- rearm ---


@pytest.mark.parametrize(
    ("outcome", "level"),
    [
        ("rearmed", "success"),
        ("not_found", "warning"),
        ("refused", "warning"),
        ("rejected", "error"),
    ],
)
def test_every_rearm_outcome_has_its_own_message(outcome: RearmOutcome, level: str):
    got_level, body = rearm_flash(RearmResult(ROW, outcome, "why"))
    assert got_level == level
    assert ROW in body


def test_every_rearm_outcome_is_covered():
    """A new outcome added to the core must get a message, not a KeyError."""
    assert set(bus_triage.REARM_MESSAGES) == set(RearmOutcome.__args__)


def test_a_refused_rearm_carries_the_cores_reason():
    _, body = rearm_flash(RearmResult(ROW, "refused", "only info.changes rows rearm"))
    assert "only info.changes rows rearm" in body


# --- reprocess ---


@pytest.mark.parametrize(
    ("outcome", "level"),
    [
        ("reprocessed", "success"),
        ("not_found", "warning"),
        ("not_owned", "warning"),
        ("deferred", "warning"),
        ("undecodable", "error"),
        ("rejected", "error"),
        ("failed", "error"),
    ],
)
def test_every_reprocess_outcome_has_its_own_message(outcome: ReprocessOutcome, level: str):
    got_level, body = reprocess_flash(ReprocessResult(ENTRY, outcome, "detail-text"))
    assert got_level == level
    assert ENTRY in body
    if outcome not in ("reprocessed", "not_found", "deferred"):
        assert "detail-text" in body


def test_every_reprocess_outcome_is_covered():
    assert set(bus_triage.REPROCESS_MESSAGES) == set(ReprocessOutcome.__args__)


def test_an_interrupted_reprocess_reports_progress_and_says_re_list():
    err = ReprocessInterruptedError(
        DLQ, results=(ReprocessResult(ENTRY, "reprocessed"),), in_doubt=None
    )
    level, body = reprocess_interrupted_flash(err)
    assert level == "error"
    assert "re-list" in body.lower()
    assert "reprocessed" in body


def test_an_interrupted_reprocess_names_the_id_in_doubt():
    err = ReprocessInterruptedError(DLQ, results=(), in_doubt=ENTRY)
    _, body = reprocess_interrupted_flash(err)
    assert ENTRY in body
    assert "in doubt" in body


# --- discard ---


def test_an_outbox_discard_says_it_was_logged():
    level, body = outbox_discard_flash(DiscardOutcome(discarded=[ROW], not_found=[]), ROW)
    assert level == "success"
    assert ROW in body
    assert "journald" in body


def test_an_outbox_discard_of_a_gone_row_is_a_warning():
    level, body = outbox_discard_flash(DiscardOutcome(discarded=[], not_found=[ROW]), ROW)
    assert level == "warning"
    assert ROW in body


def test_a_dlq_discard_says_which_queue():
    level, body = dlq_discard_flash(DiscardResult(discarded=(ENTRY,), not_found=()), DLQ, ENTRY)
    assert level == "success"
    assert ENTRY in body and DLQ in body


def test_a_dlq_discard_of_a_gone_entry_is_a_warning():
    level, _ = dlq_discard_flash(DiscardResult(discarded=(), not_found=(ENTRY,)), DLQ, ENTRY)
    assert level == "warning"


def test_an_interrupted_dlq_discard_names_the_id_in_doubt_and_says_re_list():
    err = DiscardInterruptedError(DLQ, discarded=(), not_found=(), in_doubt=ENTRY)
    level, body = dlq_discard_interrupted_flash(err)
    assert level == "error"
    assert ENTRY in body
    assert "re-list" in body.lower()


def test_an_interrupted_dlq_read_says_nothing_was_deleted():
    err = DiscardInterruptedError(DLQ, discarded=(), not_found=(), in_doubt=None)
    _, body = dlq_discard_interrupted_flash(err)
    assert "nothing was deleted" in body


# --- the discard confirmation (D4) ---


def test_an_owned_entry_confirms_plainly():
    text = discard_confirm(_entry(group="archiver.revisions"))
    assert "cannot be undone" in text
    assert "not archiver" not in text


def test_a_foreign_entry_confirmation_names_the_group_that_parked_it():
    text = discard_confirm(_entry(group="replicator.revisions"))
    assert "replicator.revisions" in text
    assert "not archiver" in text


def test_an_entry_with_no_provenance_says_nothing_proves_whose_it_is():
    text = discard_confirm(_entry(group=None))
    assert "no provenance" in text
    assert "None" not in text


# --- duplicate frames ---


def test_two_entries_from_one_frame_are_both_marked():
    a = _entry("1-0", group="archiver.revisions", source_id="9-0")
    b = _entry("2-0", group="archiver.revisions", source_id="9-0")
    c = _entry("3-0", group="archiver.revisions", source_id="8-0")
    assert duplicate_frames([a, b, c]) == {"1-0", "2-0"}


def test_entries_without_provenance_are_never_called_duplicates():
    """Nothing identifies the frame, so nothing proves two are the same one."""
    a = _entry("1-0", group=None)
    b = _entry("2-0", group=None)
    assert duplicate_frames([a, b]) == set()
