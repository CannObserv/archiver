"""The preview's and the test-send's canned inputs (archiver#367, D5-D6). Pure.

Ported from Watcher ``3ba20be`` ``src/core/notifications/preview_fixtures.py``,
with Archiver's names. One co-core event per kind, one :class:`ItemFacts`, and
two canned texts whose diff is computed by the real algorithm.

**Fidelity (Watcher #221).** The preview must show no variable a real send
lacks. The fixtures are co-core's own event models, rendered through the
composer's own context, so the variables match by construction. The item has no
tags, as no item does until #362.

**The diff** is never on the event: a send reads the two stored texts the
fingerprints name. The preview names its canned texts by their real digests and
diffs them with ``compute_change_diff``, so it shows what a send would.
"""

from datetime import UTC, datetime

from co_core.pure.models.changes import (
    ChangeDetectedEvent,
    WatchErrorEvent,
    WatchRecoveredEvent,
)
from co_core.pure.util.hashing import prefixed_sha256, sha256

from src.core.notifications.content import ItemFacts, WatchEvent
from src.core.notifications.diff import ChangeDiff, compute_change_diff

_PREVIEW_ITEM_ID = "01KPPFATBNYQGBB38SQ06DN9HY"
_PREVIEW_SOURCE_ID = "01KPPFATBNYQGBB38SQ06DN9HX"
_PREVIEW_EVENT_ID = "01KPPFATBNYQGBB38SQ06DN9HZ"
_PREVIEW_OCCURRED_AT = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)

PREVIEW_ITEM = ItemFacts(
    name="Example item",
    url="https://example.com/regulatory-page",
    domain_name="example.com",
    description="Tracks regulatory filings page",
    check_interval="1h",
)

# Canonical extracted text: chunk texts joined by "\n" (cannobserv#486), the shape
# the processor stores. Not HTML: the diff is over what the fingerprint hashes.
#
# The hearing schedule is one chunk with no sentence end, the shape of most live
# pages (Watcher #349), and the current text inserts a recording link in its
# first entry.
_PREVIOUS_SCHEDULE = (
    b"Hearing Schedule "
    b"Monday, April 6, 10:00 - 11:00, Licensing Hearing Agenda "
    b"Tuesday, April 7, 13:30 - 15:00, Rules Hearing Agenda "
    b"Monday, April 13, 10:00 - 11:00, Licensing Hearing Agenda "
    b"Tuesday, April 14, 13:30 - 15:00, Rules Hearing Agenda "
    b"Wednesday, April 15, 09:00 - 10:00, Enforcement Hearing Agenda "
    b"Monday, April 20, 10:00 - 11:00, Licensing Hearing Agenda "
    b"Tuesday, April 21, 13:30 - 15:00, Rules Hearing Agenda "
    b"Wednesday, April 22, 09:00 - 10:00, Enforcement Hearing Agenda "
    b"Monday, April 27, 10:00 - 11:00, Licensing Hearing Agenda "
    b"Tuesday, April 28, 13:30 - 15:00, Rules Hearing Agenda "
    b"Monday, May 4, 10:00 - 11:00, Licensing Hearing Agenda "
    b"Tuesday, May 5, 13:30 - 15:00, Rules Hearing Agenda "
    b"Wednesday, May 6, 09:00 - 10:00, Enforcement Hearing Agenda "
    b"Monday, May 11, 10:00 - 11:00, Licensing Hearing Agenda"
)
_CURRENT_SCHEDULE = _PREVIOUS_SCHEDULE.replace(
    b"Licensing Hearing Agenda Tuesday, April 7",
    b"Licensing Hearing Agenda Recording: April 6 hearing video Tuesday, April 7",
)

PREVIEW_PREVIOUS_TEXT = (
    b"""\
Regulatory Filings
Last updated: 2026-04-10
Hours
Mon-Fri: 9:00 - 17:00
Contact
contact@example.com
"""
    + _PREVIOUS_SCHEDULE
    + b"""
Recent filings
Application 2026-04-08
Renewal 2026-04-09"""
)

PREVIEW_CURRENT_TEXT = (
    b"""\
Regulatory Filings
Last updated: 2026-04-15
New licensing program
Apply for a license at https://example.com/apply
Contact
support@example.com
"""
    + _CURRENT_SCHEDULE
    + b"""
Recent filings
Application 2026-04-08
Renewal 2026-04-12
Renewal 2026-04-15"""
)


def _address(text: bytes) -> str:
    return prefixed_sha256(sha256(text))


def _blob_uri(text: bytes) -> str:
    return f"gs://co-gcs-processor/blobs/{_address(text).removeprefix('sha256:')}.bin"


_COMMON = {
    "occurred_at": _PREVIEW_OCCURRED_AT,
    "event_id": _PREVIEW_EVENT_ID,
    "info_item_id": _PREVIEW_ITEM_ID,
    "info_source_id": _PREVIEW_SOURCE_ID,
}

_FIXTURES: dict[str, WatchEvent] = {
    "change_detected": ChangeDetectedEvent(
        **_COMMON,
        previous_fingerprint=_address(PREVIEW_PREVIOUS_TEXT),
        current_fingerprint=_address(PREVIEW_CURRENT_TEXT),
        previous_text_uri=_blob_uri(PREVIEW_PREVIOUS_TEXT),
        current_text_uri=_blob_uri(PREVIEW_CURRENT_TEXT),
        previous_changed_at=datetime(2026, 4, 9, 17, 45, tzinfo=UTC),
    ),
    # The first alert, the common case: no reminder.
    "watch_error": WatchErrorEvent(**_COMMON, reason="http_status", status_code=503),
    "watch_recovered": WatchRecoveredEvent(
        **_COMMON, error_since=datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
    ),
}


def preview_event(event_type: str) -> WatchEvent:
    """The canned event of this kind. ``KeyError`` for an unknown one."""
    return _FIXTURES[event_type]


def preview_diff(event_type: str) -> ChangeDiff | None:
    """The diff a send would compute for the canned change; ``None`` for other events."""
    if event_type != "change_detected":
        return None
    return compute_change_diff(PREVIEW_PREVIOUS_TEXT, PREVIEW_CURRENT_TEXT)
