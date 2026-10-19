"""What the Bus triage screen tells the operator (archiver#271).

The screen is a UI over two existing rule sets, not a new policy:
``src/core/changes/outbox_triage.py`` (``docs/BUS.md``) and
``src/core/changes/dlq_triage.py`` (``docs/BUS_CONSUMERS.md`` § DLQ triage).
This module turns each core outcome into a flash and holds the two judgements
the templates need: the discard confirmation, and which entries are one frame
parked twice.

**Every outcome keeps its own message.** ``refused`` and ``rejected`` both leave
a row, for different reasons and with different remedies, so collapsing the
vocabulary to success / failure would hide the next step. The tables below are
keyed by the cores' ``Literal`` types, and a test holds them equal, so an
outcome added there fails here rather than raising ``KeyError`` on a click.

**Levels say whether anything changed.** ``success``: the row or entry is gone
or re-armed. ``warning``: nothing changed and nothing is wrong - already
triaged, refused by rule, not archiver's. ``error``: nothing changed and the
operator has something to fix or retry.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable

from src.core.changes.dlq_triage import (
    DeadLetter,
    DiscardInterruptedError,
    DiscardResult,
    ReprocessInterruptedError,
    ReprocessOutcome,
    ReprocessResult,
)
from src.core.changes.outbox_triage import DiscardOutcome, RearmOutcome, RearmResult

Flash = tuple[str, str]
"""A ``(level, body)`` pair for ``showFlash``."""

REARM_MESSAGES: dict[RearmOutcome, tuple[str, str]] = {
    "rearmed": ("success", "Re-armed outbox row {id}: it is back in the drain's queue."),
    "not_found": ("warning", "Outbox row {id} is no longer dead-lettered; nothing changed."),
    "refused": ("warning", "Rearm refused for {id}: {detail}."),
    "rejected": (
        "error",
        "Rearm rejected for {id}: the payload still fails the build, so it would "
        "dead-letter again. {detail}",
    ),
}

REPROCESS_MESSAGES: dict[ReprocessOutcome, tuple[str, str]] = {
    "reprocessed": ("success", "Reprocessed {id}: the handler settled it and it was deleted."),
    "not_found": ("warning", "{id} is no longer in the queue; nothing changed."),
    "not_owned": ("warning", "{id} left in the queue: {detail}. Only owned entries reprocess."),
    "deferred": ("warning", "The handler deferred {id}; it is still in the queue."),
    "undecodable": (
        "error",
        "{id} still does not decode: {detail}. Usually producer residue - discard it.",
    ),
    "rejected": (
        "error",
        "{id} is handler poison: {detail}. Discard it and file on the producer.",
    ),
    "failed": ("error", "Reprocessing {id} failed: {detail}. It stays; retry it."),
}


def flash_header(flash: Flash) -> str:
    """The ``HX-Trigger`` value raising one toast. ``json.dumps`` keeps it ASCII."""
    level, body = flash
    return json.dumps({"showFlash": {"level": level, "body": body}})


def rearm_flash(result: RearmResult) -> Flash:
    """The message for one rearm result."""
    level, template = REARM_MESSAGES[result.outcome]
    return level, template.format(id=result.row_id, detail=result.detail or "")


def outbox_discard_flash(outcome: DiscardOutcome, row_id: str) -> Flash:
    """The message for a one-row outbox discard."""
    if row_id in outcome.discarded:
        return "success", f"Discarded outbox row {row_id}; it was logged in full to journald."
    return "warning", f"Outbox row {row_id} is no longer dead-lettered; nothing changed."


def dlq_discard_flash(result: DiscardResult, dlq: str, entry_id: str) -> Flash:
    """The message for a one-entry DLQ discard."""
    if entry_id in result.discarded:
        return "success", f"Discarded {entry_id} from {dlq}; its frame was logged to journald."
    return "warning", f"{entry_id} is no longer in {dlq}; nothing changed."


def dlq_discard_interrupted_flash(err: DiscardInterruptedError) -> Flash:
    """A broker failure mid-discard: what is known, and re-list before retrying."""
    if err.in_doubt is None:
        known = "The read failed, so nothing was deleted."
    else:
        known = f"{err.in_doubt} is in doubt: its delete may have landed with the reply lost."
    return "error", f"Broker failed during discard from {err.dlq}. {known} Re-list before retrying."


def reprocess_flash(result: ReprocessResult) -> Flash:
    """The message for one reprocess result."""
    level, template = REPROCESS_MESSAGES[result.outcome]
    return level, template.format(id=result.entry_id, detail=result.detail or "")


def reprocess_interrupted_flash(err: ReprocessInterruptedError) -> Flash:
    """A broker failure mid-reprocess: the settled results, and what is in doubt."""
    settled = ", ".join(f"{r.entry_id} {r.outcome}" for r in err.results) or "none"
    doubt = (
        f" {err.in_doubt} is in doubt: its handler committed but the delete reply was "
        "lost, so a retry is harmless."
        if err.in_doubt
        else ""
    )
    return (
        "error",
        f"Broker failed during reprocess from {err.dlq}. Settled: {settled}.{doubt} "
        "Re-list before retrying.",
    )


def discard_confirm(entry: DeadLetter) -> str:
    """The ``hx-confirm`` text for discarding ``entry`` (D4).

    A fact stream's DLQ is shared, and discard does not filter by design: deciding
    the queue is archiver's role. So the confirmation is where the parking group
    gets read - it names a foreign group, or says no provenance proves whose it is.
    """
    group = entry.provenance.group
    if entry.owned:
        lead = f"Discard {entry.entry_id}?"
    elif group is None:
        lead = (
            f"{entry.entry_id} has no provenance - nothing proves archiver parked it. "
            "Discard anyway?"
        )
    else:
        lead = f"{entry.entry_id} was parked by {group}, not archiver. Discard anyway?"
    return f"{lead} This cannot be undone."


def duplicate_frames(entries: Iterable[DeadLetter]) -> set[str]:
    """Entry ids sharing a ``(provenance.group, provenance.source_id)`` with another.

    ``dead_letter`` XADDs before it acks, so a lost ack parks one frame twice.
    Only entries with both halves count: without provenance nothing names the
    frame, so nothing proves two entries are the same one.
    """
    entries = list(entries)

    def key(e: DeadLetter) -> tuple[str, str] | None:
        p = e.provenance
        return (p.group, p.source_id) if p.group and p.source_id else None

    counts = Counter(k for e in entries if (k := key(e)) is not None)
    return {e.entry_id for e in entries if (k := key(e)) is not None and counts[k] > 1}
