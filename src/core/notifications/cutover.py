"""The cutover instant T: which facts Archiver sends and which it only records (archiver#369, D3).

F3 hands notifications from Watcher to Archiver at one instant. Watcher sends
the facts that occurred before T; Archiver sends those at or after it. Both
compare the fact's own ``occurred_at``, so clock skew between hosts doesn't
matter. Only *both* services holding the same T, deployed before T arrives,
makes the flip free of gaps and double sends (CannObserv/watcher#376).

**One switch.** ``ARCHIVER_NOTIFY_CUTOVER_AT`` unset *is* shadow mode: there is
no separate mode flag to disagree with it. It is ``archiver.service``'s own
``Environment=`` line, never an env file, set since F3 (2026-11-06).

**Refuse, don't degrade.** A T that isn't an unambiguous UTC instant, or a T in
a process without the Notifier gate (archiver#368), refuses startup. A misread
T is a double send or a silent gap at F3, and a T with no client queues rows
nothing can drain.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime

from src.core.logging import get_logger
from src.core.models.notification_dispatch import DispatchMode

logger = get_logger(__name__)

CUTOVER_ENV = "ARCHIVER_NOTIFY_CUTOVER_AT"

# ISO 8601 with an explicit UTC offset: ``Z`` or ``+00:00``. A date alone or a
# naive time is refused: whose midnight, whose clock?
_UTC_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)",
)


class CutoverRefused(RuntimeError):
    """``ARCHIVER_NOTIFY_CUTOVER_AT`` can't be honoured; the process must not start."""


def resolve_cutover(environ: Mapping[str, str], *, notifier_configured: bool) -> datetime | None:
    """T, or ``None`` for shadow. Raises :class:`CutoverRefused` on any doubt."""
    raw = (environ.get(CUTOVER_ENV) or "").strip()
    if not raw:
        return None
    if not _UTC_INSTANT.fullmatch(raw):
        raise CutoverRefused(
            f"{CUTOVER_ENV} must be an ISO 8601 UTC instant (YYYY-MM-DDTHH:MM:SSZ), got {raw!r}"
        )
    cutover = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    if not notifier_configured:
        raise CutoverRefused(
            f"{CUTOVER_ENV} is set but Notifier is not configured: nothing could send"
        )
    return cutover


def mode_for(instant: datetime, cutover: datetime | None) -> DispatchMode:
    """``send`` iff T is set and ``instant`` is at or after it; otherwise ``shadow``."""
    return "send" if cutover is not None and instant >= cutover else "shadow"


def announce_cutover(cutover: datetime | None) -> None:
    """Say once, at startup, whether this process sends."""
    if cutover is None:
        logger.info("notify cutover: unset (shadow)")
    else:
        logger.info(
            "notify cutover: %s (facts at or after it send)",
            cutover.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
