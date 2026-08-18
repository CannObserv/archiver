"""The dashboard's half of a manual replication (archiver#171).

One module because both screens offer the action — the InfoItem hub and the
RepSpec detail — and the interesting part is identical on both: how a *refusal*
reaches the operator.

**A refusal is a 200 with a flash, never a 4xx.** htmx discards a non-2xx body
unless `response-targets` routes it somewhere, and the error envelope
`raise_422` produces is JSON, so routing it would inject an envelope into the
table. [docs/STYLE.md](../../docs/STYLE.md) states the rule directly: return the
partial at 200 and put the message where the operator will see it. The first cut
of these routes raised 422 and the four refusal conditions were invisible in the
UI (archiver#171 CR #36).
"""

from __future__ import annotations

import json

from src.core.services.replication_issuance import (
    ManualIssuanceError,
    manual_issuance_refusal,
)

FLASH_LEVEL = "error"


def refusal_flash_header(error: ManualIssuanceError) -> str:
    """``HX-Trigger`` value announcing a refused manual replication.

    Carries the operator-facing sentence from the service's own vocabulary, so
    the machine token in the logs and the message on screen cannot drift.
    """
    _code, message = manual_issuance_refusal(error)
    return json.dumps({"showFlash": {"level": FLASH_LEVEL, "body": message}})
