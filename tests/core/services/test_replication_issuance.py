"""Issuing ``content.replicate`` on a new revision (archiver#169).

One command per active assignment, minted and persisted in the *same*
transaction as the revision insert — "revision recorded" and "replication
requested" cannot diverge, which is the whole reason issuance rides the existing
outbox rather than being published from the consumer's hot path.

The properties under test are the issuer contract's, not this repo's
conveniences: MUST-1 (a fresh ``command_id`` per occasion, never derived),
MUST-2 (the mapping persisted before the publish), R1 (a rendered destination,
never a template), and R2's determinism. The skip cases matter as much as the
happy path — a replication that silently does not happen is what #171 has to
render.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from ulid import ULID

from src.core.models import (
    ChangesOutboxRow,
    InfoItem,
    InfoItemRepSpec,
    InfoItemSource,
    InfoSource,
    ReplicationCommand,
    RepSpec,
    SourceRevision,
)
from src.core.services.replication_issuance import (
    CONTENT_REPLICATE_TOPIC,
    SKIP_BLOB_ABSENT,
    SKIP_BLOB_EXPIRED,
    SKIP_DESTINATION_COLLISION,
    SKIP_UNRENDERABLE,
    STATE_REQUESTED,
    STATE_SKIPPED,
    AssignmentNotActiveError,
    AssignmentUnreachableError,
    NoActiveSourceError,
    NoRevisionError,
    issue_for_assignment,
    issue_for_revision,
)
from src.core.services.source_revision import RevisionFacts, record_revision

FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64
CAPTURED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
CAPTURED_AT_LATER = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
BLOB_URI = "file:///var/lib/replicator/blobs/aa/bb/" + "a" * 64 + ".bin"


@pytest.fixture
async def info_source(session) -> InfoSource:
    src = InfoSource(
        url="https://example.com/replication-test",
        source_specs=[
            {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}
        ],
    )
    session.add(src)
    await session.flush()
    return src


def _document(**overrides) -> dict:
    doc = {
        "provider": "gcs",
        "credentials_alias": "gcs-cannobserv-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": {"storage_class": "STANDARD"},
    }
    doc.update(overrides)
    return doc


async def _assigned_item(
    session, info_source: InfoSource, *, slug: str = "wa-lcb-notices", document: dict | None = None
) -> InfoItemRepSpec:
    """An InfoItem bound to ``info_source`` with one active RepSpec assignment."""
    doc = document or _document()
    item = InfoItem(name=f"item-{slug}", rep_fields={"info_item": {"slug": slug}})
    spec = RepSpec(provider=doc["provider"], name=f"spec-{slug}", schema_version=1, document=doc)
    session.add_all([item, spec])
    await session.flush()
    session.add(
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=info_source.info_source_id)
    )
    assignment = InfoItemRepSpec(
        info_item_id=item.info_item_id,
        rep_spec_id=spec.rep_spec_id,
        activated_at=datetime.now(UTC),
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def _revision(session, info_source: InfoSource, *, fingerprint: str = FP_A, **overrides):
    """Insert the row directly, *not* through record_revision.

    record_revision issues on insert, so going through it would have every test
    calling issue_for_revision on an already-issued revision. The wiring is
    covered on its own below; these tests are about the service.
    """
    row = SourceRevision(
        info_source_id=info_source.info_source_id,
        content_fingerprint=fingerprint,
        captured_at=overrides.pop("captured_at", CAPTURED_AT),
        content_cache_uri=overrides.pop("content_cache_uri", BLOB_URI),
        source_media_type=overrides.pop("source_media_type", "text/html"),
        **overrides,
    )
    session.add(row)
    await session.flush()
    return row


async def _commands(session) -> list[ReplicationCommand]:
    result = await session.execute(
        select(ReplicationCommand).order_by(ReplicationCommand.command_id)
    )
    return list(result.scalars().all())


async def _replicate_outbox(session) -> list[ChangesOutboxRow]:
    result = await session.execute(
        select(ChangesOutboxRow).where(ChangesOutboxRow.topic == CONTENT_REPLICATE_TOPIC)
    )
    return list(result.scalars().all())


# --- one command per active assignment ---


@pytest.mark.asyncio
async def test_one_command_per_active_assignment(session, info_source):
    first = await _assigned_item(session, info_source, slug="alpha")
    second = await _assigned_item(session, info_source, slug="beta")
    revision = await _revision(session, info_source)

    issued = await issue_for_revision(session, revision)

    assert len(issued) == 2
    targets = {str(c.info_item_rep_spec_id) for c in await _commands(session)}
    assert targets == {str(first.id), str(second.id)}


@pytest.mark.asyncio
async def test_command_row_and_outbox_row_are_written_together(session, info_source):
    """MUST-2: the mapping is durable before the publish, in one transaction."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source)

    await issue_for_revision(session, revision)

    commands = await _commands(session)
    outbox = await _replicate_outbox(session)
    assert len(commands) == 1
    assert len(outbox) == 1
    assert outbox[0].payload["command_id"] == commands[0].command_id
    assert commands[0].state == STATE_REQUESTED


@pytest.mark.asyncio
async def test_deactivated_assignment_is_not_issued(session, info_source):
    assignment = await _assigned_item(session, info_source)
    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()
    revision = await _revision(session, info_source)

    issued = await issue_for_revision(session, revision)

    assert issued == []
    assert await _commands(session) == []


@pytest.mark.asyncio
async def test_no_assignments_issues_nothing(session, info_source):
    revision = await _revision(session, info_source)

    assert await issue_for_revision(session, revision) == []
    assert await _replicate_outbox(session) == []


@pytest.mark.asyncio
async def test_deactivated_binding_excludes_the_item(session, info_source):
    """The revision reaches an InfoItem through an *active* binding only."""
    assignment = await _assigned_item(session, info_source)
    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == assignment.info_item_id)
        )
    ).scalar_one()
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()
    revision = await _revision(session, info_source)

    assert await issue_for_revision(session, revision) == []


# --- MUST-1: a fresh command_id per occasion ---


@pytest.mark.asyncio
async def test_second_occasion_for_one_assignment_mints_a_new_command_id(session, info_source):
    """The re-replication case. A derived id would break exactly here, and the
    breakage is TTL-bounded and intermittent — the trap MUST-1 documents."""
    await _assigned_item(session, info_source)
    first = await issue_for_revision(session, await _revision(session, info_source))
    second = await issue_for_revision(
        session, await _revision(session, info_source, fingerprint=FP_B)
    )

    assert first[0].command_id != second[0].command_id


@pytest.mark.asyncio
async def test_reissuing_the_same_revision_mints_a_new_command_id(session, info_source):
    """Two occasions for one (revision, assignment) pair are still two occasions."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source)

    first = await issue_for_revision(session, revision)
    second = await issue_for_revision(session, revision)

    assert first[0].command_id != second[0].command_id


# --- the emit payload ---


@pytest.mark.asyncio
async def test_emit_carries_the_rendered_destination_not_the_template(session, info_source):
    """R1: a command carrying an unrendered template is refused downstream."""
    await _assigned_item(session, info_source, slug="wa-lcb")
    revision = await _revision(session, info_source)

    await issue_for_revision(session, revision)

    payload = (await _replicate_outbox(session))[0].payload
    assert payload["destination"] == f"archive/wa-lcb/{'a' * 64}.html"
    assert "{" not in payload["destination"]


@pytest.mark.asyncio
async def test_emit_field_shape(session, info_source):
    assignment = await _assigned_item(session, info_source)
    revision = await _revision(session, info_source)

    await issue_for_revision(session, revision)

    payload = (await _replicate_outbox(session))[0].payload
    assert payload["event_type"] == "content_replicate"
    assert payload["provider"] == "gcs"
    assert payload["credentials_alias"] == "gcs-cannobserv-prod"
    assert payload["blob_uri"] == BLOB_URI
    assert payload["media_type"] == "text/html"
    assert payload["object_options"] == {"storage_class": "STANDARD"}
    assert payload["info_item_rep_spec_id"] == str(assignment.id)
    assert payload["source_revision_id"] == str(revision.source_revision_id)
    assert payload["info_source_id"] == str(info_source.info_source_id)


@pytest.mark.asyncio
async def test_media_type_falls_back_to_octet_stream(session, info_source):
    """source_media_type is nullable; the consumer cannot recover it, and a
    permanent store would otherwise hold application/octet-stream forever
    without anyone having decided that."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source, source_media_type=None)

    await issue_for_revision(session, revision)

    assert (await _replicate_outbox(session))[0].payload["media_type"] == "application/octet-stream"


# --- skips are recorded, never silent ---


@pytest.mark.asyncio
async def test_revision_without_a_blob_is_skipped_and_recorded(session, info_source):
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source, content_cache_uri=None)

    assert await issue_for_revision(session, revision) == []
    commands = await _commands(session)
    assert len(commands) == 1
    assert commands[0].state == STATE_SKIPPED
    assert commands[0].reason == SKIP_BLOB_ABSENT
    assert await _replicate_outbox(session) == []


@pytest.mark.asyncio
async def test_expired_blob_is_skipped_and_recorded(session, info_source):
    """MUST-7 inverts: the issuer schedules against the horizon. Archiver cannot
    re-fetch (Watcher issues content.fetch, #142 forbids the call), so this is
    surfaced rather than repaired."""
    await _assigned_item(session, info_source)
    revision = await _revision(
        session,
        info_source,
        content_cache_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    assert await issue_for_revision(session, revision) == []
    commands = await _commands(session)
    assert commands[0].reason == SKIP_BLOB_EXPIRED


@pytest.mark.asyncio
async def test_unknown_expiry_still_issues(session, info_source):
    """A NULL horizon records absence, not an expired blob."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source, content_cache_expires_at=None)

    assert len(await issue_for_revision(session, revision)) == 1


@pytest.mark.asyncio
async def test_unrenderable_bag_is_skipped_per_assignment(session, info_source):
    """rep_fields stays editable after assignment, so the pre-flight there is
    not a guarantee here."""
    assignment = await _assigned_item(session, info_source)
    item = await session.get(InfoItem, assignment.info_item_id)
    item.rep_fields = {"info_item": {"slug": "not a segment"}}
    await session.flush()
    revision = await _revision(session, info_source)

    assert await issue_for_revision(session, revision) == []
    commands = await _commands(session)
    assert commands[0].state == STATE_SKIPPED
    assert commands[0].reason == SKIP_UNRENDERABLE


@pytest.mark.asyncio
async def test_colliding_destinations_are_skipped_not_published(session, info_source):
    """Two assignments rendering one path: publishing both would return as
    destination_conflict, reporting a conflict rather than the path-design
    error it is."""
    document = _document(path_template="archive/{source_revision.fingerprint}.html")
    await _assigned_item(session, info_source, slug="alpha", document=document)
    await _assigned_item(session, info_source, slug="beta", document=document)
    revision = await _revision(session, info_source)

    assert await issue_for_revision(session, revision) == []
    commands = await _commands(session)
    assert len(commands) == 2
    assert {c.reason for c in commands} == {SKIP_DESTINATION_COLLISION}
    assert await _replicate_outbox(session) == []


@pytest.mark.asyncio
async def test_a_collision_does_not_silence_an_unrelated_assignment(session, info_source):
    """Only the colliding pair is skipped (CR #11).

    Assignments fail, retry and complete independently — that is MUST-1's
    argument for one command per assignment rather than one carrying a list.
    Refusing a third assignment whose destination is unique because two others
    share a path contradicts it.
    """
    shared = _document(path_template="archive/{source_revision.fingerprint}.html")
    await _assigned_item(session, info_source, slug="alpha", document=shared)
    await _assigned_item(session, info_source, slug="beta", document=shared)
    unique = await _assigned_item(session, info_source, slug="gamma")
    revision = await _revision(session, info_source)

    issued = await issue_for_revision(session, revision)

    assert [str(c.info_item_rep_spec_id) for c in issued] == [str(unique.id)]
    skipped = [c for c in await _commands(session) if c.state == STATE_SKIPPED]
    assert {c.reason for c in skipped} == {SKIP_DESTINATION_COLLISION}
    assert len(skipped) == 2
    assert len(await _replicate_outbox(session)) == 1


@pytest.mark.asyncio
async def test_unsupported_provider_is_skipped_not_raised(session, info_source):
    """The Emit variant pins provider to a Literal; an unknown one must not take
    down the consumer that is writing the revision."""
    await _assigned_item(session, info_source, document=_document(provider="s3"))
    revision = await _revision(session, info_source)

    assert await issue_for_revision(session, revision) == []
    assert (await _commands(session))[0].state == STATE_SKIPPED


# --- the write path calls it ---


@pytest.mark.asyncio
async def test_record_revision_issues_on_insert(session, info_source):
    await _assigned_item(session, info_source)

    await record_revision(
        session,
        RevisionFacts(
            info_source_id=info_source.info_source_id,
            content_fingerprint=FP_A,
            captured_at=CAPTURED_AT,
            content_cache_uri=BLOB_URI,
            source_media_type="text/html",
        ),
    )

    assert len(await _commands(session)) == 1


@pytest.mark.asyncio
async def test_record_revision_does_not_reissue_on_the_idempotent_no_op(session, info_source):
    """A redelivery is the same occasion — it must not mint a second command."""
    await _assigned_item(session, info_source)
    facts = RevisionFacts(
        info_source_id=info_source.info_source_id,
        content_fingerprint=FP_A,
        captured_at=CAPTURED_AT,
        content_cache_uri=BLOB_URI,
        source_media_type="text/html",
    )
    await record_revision(session, facts)
    _row, inserted = await record_revision(session, facts)

    assert inserted is False
    assert len(await _commands(session)) == 1


@pytest.mark.asyncio
async def test_service_does_not_commit(session, info_source):
    """The caller owns the transaction boundary — the point of the outbox."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source)

    await issue_for_revision(session, revision)
    await session.rollback()

    result = await session.execute(select(func.count()).select_from(ReplicationCommand))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_command_ids_are_ulid_shaped(session, info_source):
    """Text on the wire, ULID-shaped so issuance order is readable from the id."""
    await _assigned_item(session, info_source)
    revision = await _revision(session, info_source)

    issued = await issue_for_revision(session, revision)

    assert ULID.from_str(issued[0].command_id)


# ---------------------------------------------------------------------------
# Manual re-issue — archiver#171
# ---------------------------------------------------------------------------
#
# A new assignment on *stable* content never replicates: nothing triggers
# issuance until the next revision, which for a stable InfoItem may be never.
# `issue_for_assignment` is the operator's way out, and it is deliberately the
# same pipeline — blob guard, render, collision domain — rather than a second
# path that could drift from the automatic one.


@pytest.mark.asyncio
async def test_manual_issue_uses_the_latest_revision_of_the_active_binding(session, info_source):
    assignment = await _assigned_item(session, info_source)
    await _revision(session, info_source, fingerprint=FP_A)
    newest = await _revision(session, info_source, fingerprint=FP_B, captured_at=CAPTURED_AT_LATER)

    command = await issue_for_assignment(session, assignment)

    assert command is not None
    assert command.source_revision_id == newest.source_revision_id
    assert command.state == STATE_REQUESTED
    assert command.destination.endswith(FP_B.removeprefix("sha256:") + ".html")


@pytest.mark.asyncio
async def test_manual_issue_enqueues_the_outbox_row_in_the_caller_transaction(session, info_source):
    """MUST-2 is not relaxed for the manual path — same mapping-before-publish."""
    assignment = await _assigned_item(session, info_source)
    await _revision(session, info_source)

    command = await issue_for_assignment(session, assignment)
    await session.flush()

    rows = (
        (
            await session.execute(
                select(ChangesOutboxRow).where(ChangesOutboxRow.topic == CONTENT_REPLICATE_TOPIC)
            )
        )
        .scalars()
        .all()
    )
    assert [row.payload["command_id"] for row in rows] == [command.command_id]


@pytest.mark.asyncio
async def test_manual_issue_touches_only_the_requested_assignment(session, info_source):
    """Two active assignments on one item; re-issuing one must not re-issue the
    other, which may be mid-flight against the same revision."""
    first = await _assigned_item(session, info_source, slug="alpha")
    second = await _assigned_item(session, info_source, slug="beta")
    await _revision(session, info_source)

    command = await issue_for_assignment(session, first)

    assert command.info_item_rep_spec_id == first.id
    commands = await _commands(session)
    assert [c.info_item_rep_spec_id for c in commands] == [first.id]
    assert second.id not in {c.info_item_rep_spec_id for c in commands}


@pytest.mark.asyncio
async def test_manual_issue_refuses_a_deactivated_assignment(session, info_source):
    assignment = await _assigned_item(session, info_source)
    assignment.deactivated_at = datetime.now(UTC)
    await session.flush()
    await _revision(session, info_source)

    with pytest.raises(AssignmentNotActiveError):
        await issue_for_assignment(session, assignment)

    assert await _commands(session) == []


@pytest.mark.asyncio
async def test_manual_issue_refuses_when_the_item_has_no_active_binding(session, info_source):
    """A bare InfoItem has no source to replicate *from*. Distinct from "no
    revision yet": one is a wiring gap, the other is patience."""
    assignment = await _assigned_item(session, info_source)
    binding = (
        await session.execute(
            select(InfoItemSource).where(InfoItemSource.info_item_id == assignment.info_item_id)
        )
    ).scalar_one()
    binding.deactivated_at = datetime.now(UTC)
    await session.flush()
    await _revision(session, info_source)

    with pytest.raises(NoActiveSourceError):
        await issue_for_assignment(session, assignment)


@pytest.mark.asyncio
async def test_manual_issue_refuses_when_the_source_has_no_revision_yet(session, info_source):
    assignment = await _assigned_item(session, info_source)

    with pytest.raises(NoRevisionError):
        await issue_for_assignment(session, assignment)

    assert await _commands(session) == []


@pytest.mark.asyncio
async def test_manual_issue_records_a_skip_when_the_blob_is_gone(session, info_source):
    """Returns None rather than raising: the refusal is *recorded*, which is the
    thing #171 has to render. An exception would leave nothing behind."""
    assignment = await _assigned_item(session, info_source)
    await _revision(
        session,
        info_source,
        content_cache_uri=None,
    )

    assert await issue_for_assignment(session, assignment) is None

    commands = await _commands(session)
    assert [(c.state, c.reason) for c in commands] == [(STATE_SKIPPED, SKIP_BLOB_ABSENT)]


@pytest.mark.asyncio
async def test_manual_issue_keeps_the_full_collision_domain(session, info_source):
    """The colliding sibling is not the one being re-issued, and the destination
    is still ambiguous. Rendering the collision domain as "just this assignment"
    would let the manual path publish what the automatic path refuses."""
    fixed = _document(path_template="archive/{source_revision.id}.html", required_fields=[])
    first = await _assigned_item(session, info_source, slug="one", document=fixed)
    await _assigned_item(session, info_source, slug="two", document=fixed)
    await _revision(session, info_source)

    assert await issue_for_assignment(session, first) is None

    commands = await _commands(session)
    assert [(c.info_item_rep_spec_id, c.state, c.reason) for c in commands] == [
        (first.id, STATE_SKIPPED, SKIP_DESTINATION_COLLISION)
    ]


@pytest.mark.asyncio
async def test_manual_issue_refuses_when_the_assignment_is_not_in_its_own_domain(
    session, info_source, monkeypatch
):
    """A defensive guard, not a reachable path today.

    An empty issuance result and a *recorded skip* both used to come back as
    None, and they mean opposite things: a skip says "considered and declined,
    here is the row", while an unreachable target says nothing happened and
    nothing was written. The route renders the row either way, so the second
    case would show an older `complete` occasion and read as success (CR #31).
    """
    assignment = await _assigned_item(session, info_source)
    await _revision(session, info_source)
    monkeypatch.setattr(
        "src.core.services.replication_issuance._active_targets",
        lambda *_args, **_kwargs: _empty_targets(),
    )

    with pytest.raises(AssignmentUnreachableError):
        await issue_for_assignment(session, assignment)

    assert await _commands(session) == []


async def _empty_targets():
    return []


@pytest.mark.asyncio
async def test_a_sibling_that_cannot_render_does_not_warn_on_the_manual_path(
    session, info_source, caplog
):
    """The sibling is in the collision domain but not the caller's business, and
    it gets no skip row — so a WARNING about it is a log line with no state
    behind it, the exact thing #169's skip rows exist to eliminate (CR #30)."""
    healthy = await _assigned_item(session, info_source, slug="healthy")
    await _assigned_item(
        session,
        info_source,
        slug="broken",
        document=_document(
            path_template="archive/{info_item.missing}/{source_revision.id}.html",
            required_fields=["info_item.missing"],
        ),
    )
    await _revision(session, info_source)

    with caplog.at_level("WARNING"):
        assert await issue_for_assignment(session, healthy) is not None

    assert "cannot render a destination" not in caplog.text
