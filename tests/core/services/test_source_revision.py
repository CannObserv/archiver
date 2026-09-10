"""Tests for the SourceRevision write path (``src.core.services.source_revision``).

The path was inline in ``POST /source-revisions`` until archiver#139 needed a
second caller — the ``content.revisions`` consumer. Extracted rather than
reimplemented, because the issue's "payloads byte-identical to the HTTP path's"
is only checkable if there is one path to be identical *to*.

Covers:
1. New revision → row inserted, ``inserted=True``
2. Same (source, fingerprint) → existing row returned, ``inserted=False``
3. Different fingerprint, same source → a second row
4. New revision → exactly one outbox row, correct payload shape
5. Duplicate → no second outbox row
6. bindings reflect active bindings, ordered by info_item_id
7. Deactivated bindings excluded
8. Unknown info_source_id → UnknownInfoSourceError, nothing written
9. Caller-supplied source_revision_id honoured on insert
10. Caller-supplied id already used by a different pair → SourceRevisionIdConflictError
11. Caller-supplied id matching its own existing pair → idempotent no-op
12. The service does not commit — the caller owns the transaction boundary
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.extract import spec_fingerprint
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import ChangesOutboxRow, InfoItem, InfoItemSource, InfoSource, SourceRevision
from src.core.services.source_revision import (
    RevisionFacts,
    SourceRevisionIdConflictError,
    UnknownInfoSourceError,
    record_revision,
)

FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64
CAPTURED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
async def info_source(session) -> InfoSource:
    """InfoSource the revisions under test hang off."""
    src = InfoSource(
        url="https://example.com/service-test",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(src)
    await session.flush()
    return src


def _facts(info_source_id: ULID, fingerprint: str = FP_A, **overrides) -> RevisionFacts:
    """A minimal RevisionFacts; ``overrides`` set the optional columns."""
    return RevisionFacts(
        info_source_id=info_source_id,
        content_fingerprint=fingerprint,
        captured_at=CAPTURED_AT,
        **overrides,
    )


async def _outbox_count(session) -> int:
    result = await session.execute(select(func.count()).select_from(ChangesOutboxRow))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_new_revision_inserts_row(session, info_source):
    row, inserted = await record_revision(session, _facts(info_source.info_source_id))

    assert inserted is True
    assert row.info_source_id == info_source.info_source_id
    assert row.content_fingerprint == FP_A
    assert row.captured_at == CAPTURED_AT


@pytest.mark.asyncio
async def test_duplicate_pair_returns_existing_row(session, info_source):
    first, _ = await record_revision(session, _facts(info_source.info_source_id))
    second, inserted = await record_revision(session, _facts(info_source.info_source_id))

    assert inserted is False
    assert second.source_revision_id == first.source_revision_id


@pytest.mark.asyncio
async def test_different_fingerprint_inserts_second_row(session, info_source):
    first, _ = await record_revision(session, _facts(info_source.info_source_id, FP_A))
    second, inserted = await record_revision(session, _facts(info_source.info_source_id, FP_B))

    assert inserted is True
    assert second.source_revision_id != first.source_revision_id


@pytest.mark.asyncio
async def test_new_revision_emits_one_outbox_row(session, info_source):
    row, _ = await record_revision(session, _facts(info_source.info_source_id))

    result = await session.execute(select(ChangesOutboxRow))
    outbox = result.scalars().all()
    assert len(outbox) == 1
    assert outbox[0].topic == "info.changes"
    payload = outbox[0].payload
    assert payload["event_type"] == "source_revision_captured"
    assert payload["info_source_id"] == str(info_source.info_source_id)
    assert payload["source_revision_id"] == str(row.source_revision_id)
    assert payload["content_fingerprint"] == FP_A
    assert payload["bindings"] == []


@pytest.mark.asyncio
async def test_duplicate_emits_no_second_outbox_row(session, info_source):
    await record_revision(session, _facts(info_source.info_source_id))
    await record_revision(session, _facts(info_source.info_source_id))

    assert await _outbox_count(session) == 1


@pytest.mark.asyncio
async def test_bindings_list_active_items_ordered(session, info_source):
    items = [InfoItem(name=f"Item {n}") for n in range(3)]
    session.add_all(items)
    await session.flush()
    for item in items:
        session.add(
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=info_source.info_source_id,
            )
        )
    await session.flush()

    await record_revision(session, _facts(info_source.info_source_id))

    result = await session.execute(select(ChangesOutboxRow))
    bindings = result.scalar_one().payload["bindings"]
    ids = [b["info_item_id"] for b in bindings]
    assert ids == sorted(str(i.info_item_id) for i in items)


@pytest.mark.asyncio
async def test_deactivated_bindings_excluded(session, info_source):
    item = InfoItem(name="Deactivated")
    session.add(item)
    await session.flush()
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=info_source.info_source_id,
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.flush()

    await record_revision(session, _facts(info_source.info_source_id))

    result = await session.execute(select(ChangesOutboxRow))
    assert result.scalar_one().payload["bindings"] == []


@pytest.mark.asyncio
async def test_unknown_info_source_raises_and_writes_nothing(session):
    with pytest.raises(UnknownInfoSourceError):
        await record_revision(session, _facts(ULID()))

    assert await _outbox_count(session) == 0
    result = await session.execute(select(func.count()).select_from(SourceRevision))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_supplied_revision_id_honoured_on_insert(session, info_source):
    wanted = ULID()

    row, inserted = await record_revision(
        session, _facts(info_source.info_source_id, source_revision_id=wanted)
    )

    assert inserted is True
    assert row.source_revision_id == wanted


@pytest.mark.asyncio
async def test_supplied_revision_id_colliding_with_other_pair_raises(session, info_source):
    existing, _ = await record_revision(session, _facts(info_source.info_source_id, FP_A))

    with pytest.raises(SourceRevisionIdConflictError):
        await record_revision(
            session,
            _facts(
                info_source.info_source_id, FP_B, source_revision_id=existing.source_revision_id
            ),
        )


@pytest.mark.asyncio
async def test_supplied_revision_id_matching_own_pair_is_idempotent(session, info_source):
    first, _ = await record_revision(session, _facts(info_source.info_source_id, FP_A))

    second, inserted = await record_revision(
        session,
        _facts(info_source.info_source_id, FP_A, source_revision_id=first.source_revision_id),
    )

    assert inserted is False
    assert second.source_revision_id == first.source_revision_id


@pytest.mark.asyncio
async def test_service_leaves_the_outbox_row_pending_in_the_caller_transaction(
    session, info_source
):
    """The caller owns the transaction boundary.

    The consumer's ack-after-commit ordering and the route's single commit both
    depend on the row and its outbox event landing in *one* caller-controlled
    transaction — a commit inside the service would split them.

    Asserted on the *transaction*, not on ``session.new``. An earlier version
    checked ``session.new or session.dirty or session.identity_map``;
    ``identity_map`` is non-empty after any ``get``, so the disjunction held
    whether or not the service committed (CR round 1, finding 11). ``session.new``
    alone was right until replication issuance (archiver#169) put a SELECT after
    the outbox ``add``, whose autoflush moves the row out of ``new`` — a flush
    inside the caller's transaction, which is not what this test is about.
    """
    await record_revision(session, _facts(info_source.info_source_id))

    assert session.in_transaction(), "the service must not commit"
    assert await _outbox_count(session) == 1
    # Uncommitted: rolling the caller's transaction back takes the row with it.
    await session.rollback()
    assert await _outbox_count(session) == 0


@pytest.mark.asyncio
async def test_provenance_facts_persist(session, info_source):
    """The three observation-provenance fields reach their columns (archiver#139)."""
    row, inserted = await record_revision(
        session,
        _facts(
            info_source.info_source_id,
            source_media_type="text/html",
            spec_fingerprint="sha256:" + "e" * 64,
            command_id="cmd-7",
        ),
    )

    assert inserted is True
    assert row.source_media_type == "text/html"
    assert row.spec_fingerprint == "sha256:" + "e" * 64
    assert row.command_id == "cmd-7"


@pytest.mark.asyncio
async def test_spec_fingerprint_mismatch_does_not_block_the_write(session, info_source):
    """A spec_fingerprint unrelated to the InfoSource's current specs still records.

    Record-and-flag, never reject (archiver#139): archiver#140 makes source_specs
    delivery eventually consistent, so a producer extracting under a superseded
    spec is an expected transient state rather than an error — and Archiver
    cannot derive the expected value to compare against in any case
    (cannobserv#309).
    """
    row, inserted = await record_revision(
        session, _facts(info_source.info_source_id, spec_fingerprint="sha256:" + "0" * 64)
    )

    assert inserted is True
    assert row.spec_fingerprint == "sha256:" + "0" * 64


# ---------------------------------------------------------------------------
# spec_fingerprint comparison — the flag half (cannobserv#309)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_spec_fingerprint_records_current_and_position(session, info_source):
    observed = spec_fingerprint(info_source.source_specs[0])

    row, _ = await record_revision(
        session, _facts(info_source.info_source_id, spec_fingerprint=observed)
    )

    assert row.spec_match == "current"
    assert row.spec_position == 0


@pytest.mark.asyncio
async def test_superseded_spec_fingerprint_is_flagged_not_rejected(session, info_source):
    """The flag is a recorded outcome; the revision is still written.

    archiver#140 makes spec delivery eventually consistent, so a producer one
    announcement behind is an expected transient state — and the content it
    observed is real either way.
    """
    retired = {"schema_version": 1, "extraction": {"algorithm": "css", "selector": ".gone"}}

    row, inserted = await record_revision(
        session,
        _facts(info_source.info_source_id, spec_fingerprint=spec_fingerprint(retired)),
    )

    assert inserted is True
    assert row.spec_match == "superseded"
    assert row.spec_position is None


@pytest.mark.asyncio
async def test_unrecognised_derivation_is_incomparable_not_superseded(session, info_source):
    row, _ = await record_revision(
        session,
        _facts(info_source.info_source_id, spec_fingerprint="spec99:sha256:" + "a" * 64),
    )

    assert row.spec_match == "incomparable"


@pytest.mark.asyncio
async def test_absent_spec_fingerprint_leaves_the_comparison_null(session, info_source):
    """The HTTP path supplies none, so it must not read as a mismatch."""
    row, _ = await record_revision(session, _facts(info_source.info_source_id))

    assert row.spec_fingerprint is None
    assert row.spec_match is None
    assert row.spec_position is None


# ---------------------------------------------------------------------------
# The comparison on the idempotent no-op path — CR round 3, findings 21 and 25
# ---------------------------------------------------------------------------
#
# The interaction between "record the comparison" and "the second write is a
# no-op" was untested in either direction, which is how the stale verdict got
# in: the row kept the *first* observation's answer, so moving the registry to a
# new spec and re-observing already-recorded content left the row asserting
# `current` for a spec we no longer held — and that is the stuck-producer case
# the column exists to catch.

SPEC_B = {
    "schema_version": 1,
    "extraction": {"algorithm": "css", "selector": "#replacement"},
    "fingerprint": {},
}


@pytest.mark.asyncio
async def test_reobservation_under_a_superseded_spec_refreshes_the_verdict(session, info_source):
    """The row carries the most recent observation's verdict, not the first."""
    original = info_source.source_specs[0]
    await record_revision(
        session, _facts(info_source.info_source_id, spec_fingerprint=spec_fingerprint(original))
    )

    # The registry moves on; the producer is still extracting under the old spec.
    info_source.source_specs = [SPEC_B]
    await session.flush()

    row, inserted = await record_revision(
        session, _facts(info_source.info_source_id, spec_fingerprint=spec_fingerprint(original))
    )

    assert inserted is False
    assert row.spec_match == "superseded"
    assert row.spec_position is None


@pytest.mark.asyncio
async def test_reobservation_moves_all_three_columns_together(session, info_source):
    """A spec_match describing a different spec_fingerprint than the stored one
    is internally inconsistent — worse than either being stale."""
    await record_revision(
        session,
        _facts(
            info_source.info_source_id,
            spec_fingerprint=spec_fingerprint(info_source.source_specs[0]),
        ),
    )

    info_source.source_specs = [SPEC_B]
    await session.flush()
    row, _ = await record_revision(
        session, _facts(info_source.info_source_id, spec_fingerprint=spec_fingerprint(SPEC_B))
    )

    assert row.spec_fingerprint == spec_fingerprint(SPEC_B)
    assert row.spec_match == "current"
    assert row.spec_position == 0


@pytest.mark.asyncio
async def test_reobservation_writes_no_second_outbox_event(session, info_source):
    """Refreshing the verdict is not a change to the revision's identity."""
    observed = spec_fingerprint(info_source.source_specs[0])
    await record_revision(session, _facts(info_source.info_source_id, spec_fingerprint=observed))
    info_source.source_specs = [SPEC_B]
    await session.flush()

    await record_revision(session, _facts(info_source.info_source_id, spec_fingerprint=observed))

    assert await _outbox_count(session) == 1


@pytest.mark.asyncio
async def test_http_repost_does_not_erase_a_bus_written_verdict(session, info_source):
    """The HTTP path reports no fingerprint; absence must not blank what the bus knew."""
    observed = spec_fingerprint(info_source.source_specs[0])
    await record_revision(session, _facts(info_source.info_source_id, spec_fingerprint=observed))

    # A re-POST of the same revision, carrying no spec information at all.
    row, inserted = await record_revision(session, _facts(info_source.info_source_id))

    assert inserted is False
    assert row.spec_fingerprint == observed
    assert row.spec_match == "current"
    assert row.spec_position == 0


@pytest.mark.asyncio
async def test_unchanged_redelivery_does_not_relog_the_flag(session, info_source):
    """The flag fires once per state transition, not once per delivery.

    At-least-once means the same superseded observation arrives repeatedly; the
    publisher throttles its repeated conditions for the same reason.
    """
    retired = {"schema_version": 1, "extraction": {"algorithm": "css", "selector": ".gone"}}
    observed = spec_fingerprint(retired)
    facts = _facts(info_source.info_source_id, spec_fingerprint=observed)

    with patch("src.core.services.source_revision.logger") as first_log:
        await record_revision(session, facts)
    with patch("src.core.services.source_revision.logger") as second_log:
        await record_revision(session, facts)

    assert first_log.warning.call_count == 1
    assert second_log.warning.call_count == 0


# ---------------------------------------------------------------------------
# Blob reference refresh on re-observation
#
# Replicator's blob TTL runs from the blob's *last reference*, so a full
# re-fetch of unchanged bytes re-announces a later ``blob_expires_at``. The row
# kept the first observation's horizon, and a stable item read as unreplicable
# (``blob_expired_locally``) after seven days while its blob was still there -
# with no later revision ever arriving to correct it.
# ---------------------------------------------------------------------------

BLOB_URI = "gs://co-gcs-blobs/blobs/" + "a" * 64 + ".bin"
BLOB_URI_LEGACY = "file:///var/lib/replicator/blobs/aa/aa/" + "a" * 64 + ".bin"
HORIZON = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
LATER_HORIZON = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _cached(info_source_id: ULID, uri: str | None, expires_at: datetime | None) -> RevisionFacts:
    return _facts(info_source_id, content_cache_uri=uri, content_cache_expires_at=expires_at)


@pytest.mark.asyncio
async def test_reobservation_with_a_later_horizon_refreshes_the_blob_reference(
    session, info_source
):
    """The row describes the most recent observation's blob, not the first's -
    URI and horizon together, since the 2026-08-20 backend flip moved the URI."""
    await record_revision(session, _cached(info_source.info_source_id, BLOB_URI_LEGACY, HORIZON))

    row, inserted = await record_revision(
        session, _cached(info_source.info_source_id, BLOB_URI, LATER_HORIZON)
    )

    assert inserted is False
    assert row.content_cache_uri == BLOB_URI
    assert row.content_cache_expires_at == LATER_HORIZON


@pytest.mark.asyncio
@pytest.mark.parametrize("redelivered_horizon", [HORIZON, LATER_HORIZON])
async def test_the_horizon_only_moves_forward(session, info_source, redelivered_horizon):
    """A redelivered older observation is ignored; an equal one is the same emission."""
    await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, LATER_HORIZON))

    row, _ = await record_revision(
        session, _cached(info_source.info_source_id, BLOB_URI_LEGACY, redelivered_horizon)
    )

    assert row.content_cache_uri == BLOB_URI
    assert row.content_cache_expires_at == LATER_HORIZON


@pytest.mark.asyncio
async def test_an_absent_reference_never_erases_a_stored_one(session, info_source):
    """The HTTP path carries no blob; a re-POST must not blank what the bus knew."""
    await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, HORIZON))

    row, _ = await record_revision(session, _facts(info_source.info_source_id))

    assert row.content_cache_uri == BLOB_URI
    assert row.content_cache_expires_at == HORIZON


@pytest.mark.asyncio
async def test_an_unknown_horizon_never_replaces_a_known_one(session, info_source):
    """``None`` records absence, never a guess - it cannot be ordered against a date."""
    await record_revision(session, _cached(info_source.info_source_id, BLOB_URI_LEGACY, HORIZON))

    row, _ = await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, None))

    assert row.content_cache_uri == BLOB_URI_LEGACY
    assert row.content_cache_expires_at == HORIZON


@pytest.mark.asyncio
async def test_a_known_horizon_replaces_an_unknown_one(session, info_source):
    await record_revision(session, _cached(info_source.info_source_id, BLOB_URI_LEGACY, None))

    row, _ = await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, HORIZON))

    assert row.content_cache_uri == BLOB_URI
    assert row.content_cache_expires_at == HORIZON


@pytest.mark.asyncio
async def test_a_row_recorded_without_a_blob_takes_the_first_reference_offered(
    session, info_source
):
    """A revision authored over HTTP and later observed on the bus gains a reference."""
    await record_revision(session, _facts(info_source.info_source_id))

    row, _ = await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, HORIZON))

    assert row.content_cache_uri == BLOB_URI
    assert row.content_cache_expires_at == HORIZON


@pytest.mark.asyncio
async def test_blob_refresh_emits_no_event_and_issues_no_replication(session, info_source):
    """The revision's identity is unchanged: no outbox row, and no second occasion."""
    with patch("src.core.services.source_revision.issue_for_revision") as issue:
        await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, HORIZON))
        await record_revision(session, _cached(info_source.info_source_id, BLOB_URI, LATER_HORIZON))

    assert issue.await_count == 1
    assert await _outbox_count(session) == 1
