"""The dashboard's half of a manual replication (archiver#171).

One module because both screens offer the action — the InfoItem hub and the
RepSpec detail — and the interesting part is identical on both: what the
operator is told.

**A refusal is a 200 with a flash, never a 4xx.** htmx discards a non-2xx body
unless `response-targets` routes it somewhere, and the error envelope
`raise_422` produces is JSON, so routing it would inject an envelope into the
table. `docs/STYLE.md` states the rule directly: return the partial at 200 and
put the message where the operator will see it. The first cut of these routes
raised 422 and the four refusal conditions were invisible in the UI (CR #36).

**Success is announced too.** This is the one dashboard action that writes into a
store which cannot be deleted, and it used to confirm itself only by a badge
changing in a table that had just re-rendered wholesale. Flashing failures while
staying silent on the irreversible outcome is the wrong way round (CR #42).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.core.models import ReplicationCommand
from src.core.services.replication_issuance import (
    STATE_REQUESTED,
    ManualIssuanceError,
    manual_issuance_refusal,
)

# Archiver's own token for "the registry declined, but did not say why" — only
# reachable if a skip row fails to come back from the read after the commit.
UNKNOWN_SKIP_REASON = "reason unavailable"

# How long the section keeps asking, and how often (archiver#212). The observed
# round trip is under a second, so two seconds is several ticks of headroom and
# a load of one query per open command per operator watching.
#
# The window exists because ``requested`` is not bounded by the round trip: the
# reaper closes an unanswered command after six hours
# (``DEFAULT_REAP_HORIZON``), and polling to *that* would leave a forgotten tab
# asking every two seconds all afternoon. Past the window the section stops and
# says the command is still open, which is the honest report — Replicator has
# neither refused nor finished, and a transient retry publishes no fact.
POLL_INTERVAL_SECONDS = 2
POLL_WINDOW = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class LivePoll:
    """Whether the assignments section should keep asking, and what to say."""

    active: bool
    stalled: bool


def live_poll(
    latest_commands: Mapping[object, ReplicationCommand],
    *,
    now: datetime | None = None,
) -> LivePoll:
    """Decide whether the section is waiting on a fact that has not arrived.

    Derived from the same rows the badges render from, so the swap that lands a
    terminal state is the swap that drops the polling attributes. Nothing has to
    decide to be the last tick, and a poll cannot outlive what it was watching.

    ``stalled`` is the open-but-past-the-window case, kept separate from
    ``active`` being false so the template can distinguish "nothing pending"
    from "still pending, no longer watching" — reporting the second as the
    first would be a settled row that is not settled.
    """
    now = now or datetime.now(UTC)
    open_commands = [c for c in latest_commands.values() if c.state == STATE_REQUESTED]
    if not open_commands:
        return LivePoll(active=False, stalled=False)
    # The youngest decides: one fresh command is worth watching even beside an
    # older one that has already outrun the window.
    youngest = max(c.issued_at for c in open_commands)
    if youngest.tzinfo is None:
        youngest = youngest.replace(tzinfo=UTC)
    return LivePoll(active=now - youngest < POLL_WINDOW, stalled=now - youngest >= POLL_WINDOW)


def outcome_flash_header(
    *,
    refusal: ManualIssuanceError | None,
    issued: ReplicationCommand | None,
    latest: ReplicationCommand | None,
) -> str:
    """``HX-Trigger`` value describing what one Replicate click actually did.

    Three outcomes, checked in the order they override each other:

    - **refused** — the service would not even record an occasion. Reported at
      ``error`` with the service's own sentence, so the token in the logs and the
      message on screen cannot drift. Checked *first*: ``latest`` on this path is
      some earlier occasion, and reporting it would announce a success the
      operator did not just cause.
    - **issued** — a command went to the outbox. ``success``, naming the rendered
      destination, which is the part worth reading back before it becomes a
      permanent artifact.
    - **skipped** — an occasion was considered and declined, and the row for it is
      in ``latest``. ``warning`` rather than ``error``: nothing failed, and the
      reason is a condition the operator can usually fix.
    """
    if refusal is not None:
        _code, message = manual_issuance_refusal(refusal)
        return _flash("error", message)
    if issued is not None:
        return _flash("success", f"Replication requested → {issued.destination}")
    reason = (latest.reason if latest is not None else None) or UNKNOWN_SKIP_REASON
    return _flash("warning", f"Replication skipped: {reason}")


def _flash(level: str, body: str) -> str:
    return json.dumps({"showFlash": {"level": level, "body": body}})
