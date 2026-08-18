"""The manual-replication outcome→flash translation (archiver#171).

`src/dashboard/replication_actions.py` is small but it is the only place that
answers "what does the operator see?" for an action that writes into a store
which cannot be deleted. Three outcomes, three levels, and one of them is a
fallback that exists precisely because it should never fire.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ulid import ULID

from src.core.models import ReplicationCommand
from src.core.services.replication_issuance import (
    STATE_REQUESTED,
    STATE_SKIPPED,
    ManualIssuanceError,
    NoRevisionError,
)
from src.dashboard.replication_actions import outcome_flash_header


def _command(**kw) -> ReplicationCommand:
    return ReplicationCommand(
        command_id=kw.pop("command_id", "cmd-flash"),
        info_item_rep_spec_id=ULID(),
        source_revision_id=ULID(),
        info_source_id=ULID(),
        provider="gcs",
        credentials_alias="default",
        media_type="text/html",
        issued_at=datetime(2026, 8, 18, tzinfo=UTC),
        **kw,
    )


def _flash(header: str) -> dict:
    return json.loads(header)["showFlash"]


def test_an_issued_occasion_confirms_at_success_level():
    """The reversible outcomes were silent while every failure shouted — backwards
    for the one action that writes somewhere permanent (CR #42)."""
    issued = _command(state=STATE_REQUESTED, destination="archive/wa-lcb/abc.html")

    flash = _flash(outcome_flash_header(refusal=None, issued=issued, latest=issued))

    assert flash["level"] == "success"
    assert "archive/wa-lcb/abc.html" in flash["body"]


def test_a_recorded_skip_warns_and_names_the_reason():
    skip = _command(state=STATE_SKIPPED, reason="blob_expired_locally")

    flash = _flash(outcome_flash_header(refusal=None, issued=None, latest=skip))

    assert flash["level"] == "warning"
    assert "blob_expired_locally" in flash["body"]


def test_a_skip_whose_row_did_not_come_back_still_warns():
    """Defensive: `latest` is read back from the database after the commit, so a
    lost race must not turn a refusal into a success message."""
    flash = _flash(outcome_flash_header(refusal=None, issued=None, latest=None))

    assert flash["level"] == "warning"


def test_a_refusal_reports_at_error_level_with_the_service_vocabulary():
    error = NoRevisionError(ULID())

    flash = _flash(outcome_flash_header(refusal=error, issued=None, latest=None))

    assert flash["level"] == "error"
    assert "not been captured yet" in flash["body"]


def test_an_unregistered_refusal_falls_back_rather_than_raising():
    """The vocabulary lives beside its exceptions (CR #34) so this cannot happen
    by accident — but a KeyError here would 500 a designed refusal (CR #28)."""
    flash = _flash(
        outcome_flash_header(
            refusal=ManualIssuanceError(ULID(), "nobody registered this"),
            issued=None,
            latest=None,
        )
    )

    assert flash["level"] == "error"
    assert flash["body"] == "This replication could not be issued"


def test_a_refusal_outranks_a_stale_latest_row():
    """`latest` is whatever the assignment's newest occasion is, which on a
    refusal is some *earlier* occasion — reporting it would announce a success
    the operator did not just cause."""
    earlier = _command(state="complete", public_url="https://cdn.example.com/x.json")

    flash = _flash(
        outcome_flash_header(refusal=NoRevisionError(ULID()), issued=None, latest=earlier)
    )

    assert flash["level"] == "error"
