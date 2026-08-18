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

from src.core.models import ReplicationCommand
from src.core.services.replication_issuance import (
    ManualIssuanceError,
    manual_issuance_refusal,
)

# Archiver's own token for "the registry declined, but did not say why" — only
# reachable if a skip row fails to come back from the read after the commit.
UNKNOWN_SKIP_REASON = "reason unavailable"


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
