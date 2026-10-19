"""The Bus triage screen and its row actions (archiver#271).

One screen over the two triage modules: the outbox's dead-lettered rows
(``outbox_triage``, a database read, so it works bus-dormant) and each queue in
``TRIAGE_DLQS`` (``dlq_triage``, a broker read). The DLQ tests hand the routes a
fakeredis instance through ``get_redis_client``, so XRANGE / XDEL run for real.
"""

import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from co_core.pure.adapters.bus.dead_letter import dead_letter_fields
from co_core.pure.adapters.bus.envelope import to_wire
from co_core.pure.models.changes import SourceRevisionObservedEvent
from fakeredis import aioredis as fakeredis_aio
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from src.api.deps import get_db_session_factory, get_redis_client
from src.api.main import app
from src.core.changes.dlq_triage import TRIAGE_DLQS
from src.core.models import AppUser, ChangesOutboxRow
from src.dashboard.routes import bus_triage as bus_triage_routes
from tests.dashboard.conftest import read_flash

_HEADERS = {"X-ExeDev-UserID": "ext-triage", "X-ExeDev-Email": "triage@example.com"}
PAGE = "/dashboard/bus-triage"
OUTBOX = f"{PAGE}/outbox"
DLQ = "content.revisions.dlq"
DLQ_URL = f"{PAGE}/dlq/{DLQ}"

_T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def _captured_event() -> dict:
    """A full, publishable ``source_revision_captured`` payload."""
    return {
        "schema_version": 2,
        "event_type": "source_revision_captured",
        "occurred_at": "2026-07-28T12:00:00+00:00",
        "info_source_id": "01HZZ000000000000000000001",
        "source_revision_id": "rev-1",
        "content_fingerprint": "sha256:" + "a" * 64,
        "bindings": [{"info_item_id": "01HZZ000000000000000000003"}],
    }


async def _dead_lettered(session, *, topic="info.changes", payload=None) -> ChangesOutboxRow:
    row = ChangesOutboxRow(
        topic=topic,
        payload=payload if payload is not None else _captured_event(),
        dead_lettered_at=_T0,
        publish_attempts=100_000,
        last_error="WRONGTYPE Operation against a key holding the wrong kind",
    )
    session.add(row)
    await session.flush()
    return row


def _observed_wire(info_source_id: str, fingerprint: str = "sha256:" + "c" * 64) -> dict[str, str]:
    return to_wire(
        SourceRevisionObservedEvent(
            occurred_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            info_source_id=info_source_id,
            extracted_fingerprint=fingerprint,
            captured_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
            content_size_bytes=10,
            content_media_type="text/plain",
            source_media_type="text/html",
            blob_uri="file:///blob",
            command_id="cmd-dashboard",
        )
    )


async def _park(
    fake_redis,
    frame: dict[str, str] | None = None,
    *,
    group: str | None = "archiver.revisions",
    source_id: str = "9-0",
    reason: str = "undecodable: BusMessageUnknownEventTypeError('x')",
    dlq: str = DLQ,
) -> str:
    frame = frame if frame is not None else {"event_type": "nope", "payload": "{}"}
    if group is None:
        fields = frame
    else:
        fields = dead_letter_fields(
            frame, source_id=source_id, group=group, consumer=f"{group}-1", reason=reason
        )
    return (await fake_redis.xadd(dlq, fields)).decode()


@pytest.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis()
    app.dependency_overrides[get_redis_client] = lambda: r
    yield r
    await r.aclose()


@pytest.fixture
def dormant(monkeypatch):
    monkeypatch.delenv("ARCHIVER_REDIS_URL", raising=False)
    app.dependency_overrides[get_redis_client] = lambda: None


@pytest.fixture
def db_factory(test_engine):
    """Reprocess runs the consumer's handler, which opens its own sessions."""
    app.dependency_overrides[get_db_session_factory] = lambda: async_sessionmaker(
        bind=test_engine, expire_on_commit=False
    )


def _row_present(html: str, row_id: str) -> bool:
    return f'id="outbox-row-{row_id}"' in html


def _entry_present(html: str, entry_id: str) -> bool:
    return f'data-entry-id="{entry_id}"' in html


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


async def test_the_page_requires_a_dashboard_login(client):
    r = await client.get(PAGE, follow_redirects=False)
    assert r.status_code == 307
    assert "/__exe.dev/login" in r.headers["location"]


async def test_the_page_has_an_outbox_section_and_one_per_triage_dlq(client, fake_redis):
    r = await client.get(PAGE, headers=_HEADERS)
    assert r.status_code == 200
    assert 'id="triage-outbox"' in r.text
    assert TRIAGE_DLQS, "non-vacuity: the allowlist is derived from OWNED_GROUPS"
    for dlq in TRIAGE_DLQS:
        assert f'hx-get="{PAGE}/dlq/{dlq}' in r.text or f"{PAGE}/dlq/{dlq}" in r.text
        assert dlq in r.text


async def test_the_page_renders_bus_dormant(client, dormant):
    """The outbox section is a database read; it still renders with no broker."""
    r = await client.get(PAGE, headers=_HEADERS)
    assert r.status_code == 200
    assert 'id="triage-outbox"' in r.text
    assert "dormant" in r.text


# ---------------------------------------------------------------------------
# Outbox section
# ---------------------------------------------------------------------------


async def test_the_outbox_section_lists_dead_lettered_rows_only(client, session):
    row = await _dead_lettered(session)
    live = ChangesOutboxRow(topic="info.changes", payload=_captured_event())
    session.add(live)
    await session.flush()

    r = await client.get(OUTBOX, headers=_HEADERS)

    assert r.status_code == 200
    assert _row_present(r.text, str(row.id))
    assert not _row_present(r.text, str(live.id))
    assert "source_revision_captured" in r.text
    assert "WRONGTYPE" in r.text
    assert "100000" in r.text


async def test_the_outbox_section_says_when_it_is_empty(client):
    r = await client.get(OUTBOX, headers=_HEADERS)
    assert "No dead-lettered outbox rows" in r.text


async def test_rearm_is_offered_only_where_the_topic_rearms(client, session):
    ok = await _dead_lettered(session)
    refused = await _dead_lettered(session, topic="info.registry")

    r = await client.get(OUTBOX, headers=_HEADERS)

    assert f'hx-post="{OUTBOX}/{ok.id}/rearm' in r.text
    assert f'hx-post="{OUTBOX}/{refused.id}/rearm' not in r.text
    assert f'hx-post="{OUTBOX}/{refused.id}/discard' in r.text


async def test_outbox_discard_asks_for_confirmation(client, session):
    row = await _dead_lettered(session)
    r = await client.get(OUTBOX, headers=_HEADERS)
    assert "hx-confirm=" in r.text
    assert "cannot be undone" in r.text
    assert str(row.id) in r.text


async def test_an_outbox_payload_is_escaped(client, session):
    await _dead_lettered(session, payload={"event_type": "<script>alert(1)</script>"})
    r = await client.get(OUTBOX, headers=_HEADERS)
    assert "<script>alert(1)</script>" not in r.text


async def test_the_outbox_section_clamps_hostile_pagination(client):
    r = await client.get(f"{OUTBOX}?limit=abc&offset=-5", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


async def test_the_outbox_section_pages(client, session):
    rows = [await _dead_lettered(session) for _ in range(3)]
    r = await client.get(f"{OUTBOX}?limit=2", headers=_HEADERS)
    shown = [row for row in rows if _row_present(r.text, str(row.id))]
    assert len(shown) <= 2
    assert f"{OUTBOX}?offset=2&amp;limit=2" in r.text


# ---------------------------------------------------------------------------
# Outbox actions
# ---------------------------------------------------------------------------


async def test_rearm_returns_the_row_to_the_drain(client, session):
    row = await _dead_lettered(session)

    r = await client.post(f"{OUTBOX}/{row.id}/rearm", headers=_HEADERS)

    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert not _row_present(r.text, str(row.id))
    await session.refresh(row)
    assert row.dead_lettered_at is None


async def test_a_refused_rearm_is_a_200_with_the_reason(client, session):
    row = await _dead_lettered(session, topic="info.registry")

    r = await client.post(f"{OUTBOX}/{row.id}/rearm", headers=_HEADERS)

    assert r.status_code == 200
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "warning"
    assert "info.registry" in flash["body"]
    assert _row_present(r.text, str(row.id))


async def test_a_rejected_rearm_is_an_error_flash(client, session):
    row = await _dead_lettered(session, payload={"event_type": "nope"})
    r = await client.post(f"{OUTBOX}/{row.id}/rearm", headers=_HEADERS)
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "error"
    assert _row_present(r.text, str(row.id))


async def test_rearming_a_row_already_triaged_is_a_warning(client):
    r = await client.post(f"{OUTBOX}/{ULID()}/rearm", headers=_HEADERS)
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "warning"


@pytest.mark.parametrize("action", ["rearm", "discard"])
async def test_a_malformed_row_id_is_a_flash_not_a_500(client, action):
    r = await client.post(f"{OUTBOX}/not-a-ulid/{action}", headers=_HEADERS)
    assert r.status_code == 200
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "error"
    assert "not-a-ulid" in flash["body"]


async def test_discard_deletes_the_row(client, session):
    row = await _dead_lettered(session)
    row_id = row.id

    r = await client.post(f"{OUTBOX}/{row_id}/discard", headers=_HEADERS)

    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert not _row_present(r.text, str(row_id))
    session.expunge_all()
    gone = await session.execute(select(ChangesOutboxRow).where(ChangesOutboxRow.id == row_id))
    assert gone.scalar_one_or_none() is None


async def test_an_action_keeps_the_page_it_was_taken_on(client, session):
    row = await _dead_lettered(session)
    r = await client.post(f"{OUTBOX}/{row.id}/discard?limit=7&offset=0", headers=_HEADERS)
    assert "limit=7" in r.text


async def test_outbox_actions_work_bus_dormant(client, session, dormant):
    row = await _dead_lettered(session)
    r = await client.post(f"{OUTBOX}/{row.id}/rearm", headers=_HEADERS)
    assert read_flash(r)["showFlash"]["level"] == "success"


async def test_outbox_actions_require_a_dashboard_login(client, session):
    row = await _dead_lettered(session)
    r = await client.post(f"{OUTBOX}/{row.id}/discard", follow_redirects=False)
    assert r.status_code == 307
    await session.refresh(row)
    assert row.dead_lettered_at is not None


# ---------------------------------------------------------------------------
# DLQ section
# ---------------------------------------------------------------------------


async def test_an_unknown_queue_is_a_404(client, fake_redis):
    for path in ("content.fetch.dlq", "content.revisions"):
        r = await client.get(f"{PAGE}/dlq/{path}", headers=_HEADERS)
        assert r.status_code == 404


async def test_an_action_on_an_unknown_queue_is_a_404(client, fake_redis):
    await fake_redis.xadd("content.revisions", {"k": "v"})
    r = await client.post(f"{PAGE}/dlq/content.revisions/1-0/discard", headers=_HEADERS)
    assert r.status_code == 404
    assert await fake_redis.xlen("content.revisions") == 1


async def test_a_dormant_bus_is_not_an_empty_queue(client, dormant):
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert r.status_code == 200
    assert "dormant" in r.text
    assert "No dead letters" not in r.text


async def test_a_bus_that_failed_init_says_so(client, monkeypatch):
    monkeypatch.setenv("ARCHIVER_REDIS_URL", "redis://127.0.0.1:6380/0")
    app.dependency_overrides[get_redis_client] = lambda: None
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert "init failed" in r.text
    assert "No dead letters" not in r.text


async def test_an_unreadable_broker_is_not_an_empty_queue(client, fake_redis):
    async def broken(*_a, **_kw):
        raise RedisConnectionError("broker went away")

    with patch.object(fake_redis, "xrange", broken):
        r = await client.get(DLQ_URL, headers=_HEADERS)

    assert r.status_code == 200
    assert "unreadable" in r.text
    # error_text's class-only form: a broker message can carry the URL.
    assert "ConnectionError" in r.text
    assert "No dead letters" not in r.text


async def test_a_hung_broker_is_bounded(client, fake_redis, monkeypatch):
    monkeypatch.setattr(bus_triage_routes, "BROKER_READ_TIMEOUT_SECONDS", 0.05)

    async def hang(*_a, **_kw):
        await asyncio.sleep(10)

    with patch.object(fake_redis, "xrange", hang):
        r = await client.get(DLQ_URL, headers=_HEADERS)

    assert r.status_code == 200
    assert "unreadable" in r.text
    assert "0.05s" in r.text


async def test_an_empty_queue_says_so(client, fake_redis):
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert "No dead letters" in r.text


async def test_an_owned_entry_offers_reprocess_and_discard(client, fake_redis):
    entry = await _park(fake_redis)

    r = await client.get(DLQ_URL, headers=_HEADERS)

    assert _entry_present(r.text, entry)
    assert f'hx-post="{DLQ_URL}/{entry}/reprocess' in r.text
    assert f'hx-post="{DLQ_URL}/{entry}/discard' in r.text
    assert "archiver.revisions" in r.text
    assert "undecodable" in r.text


async def test_a_foreign_entry_names_its_group_and_cannot_be_reprocessed(client, fake_redis):
    entry = await _park(fake_redis, group="replicator.revisions")

    r = await client.get(DLQ_URL, headers=_HEADERS)

    assert f'hx-post="{DLQ_URL}/{entry}/reprocess' not in r.text
    assert f'hx-post="{DLQ_URL}/{entry}/discard' in r.text
    assert "replicator.revisions" in r.text
    assert "not archiver" in r.text


async def test_an_entry_with_no_provenance_cannot_be_reprocessed(client, fake_redis):
    entry = await _park(fake_redis, group=None)
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert f'hx-post="{DLQ_URL}/{entry}/reprocess' not in r.text
    assert "no provenance" in r.text


async def test_the_decode_verdict_is_shown(client, fake_redis):
    """``decodes`` is the version-skew question; the screen answers it per entry."""
    skew = await _park(fake_redis, _observed_wire(str(ULID())), source_id="1-0")
    residue = await _park(fake_redis, source_id="2-0")

    r = await client.get(DLQ_URL, headers=_HEADERS)

    assert _entry_present(r.text, skew) and _entry_present(r.text, residue)
    assert "decodes" in r.text
    assert "BusMessageUnknownEventTypeError" in r.text


async def test_a_frame_parked_twice_is_marked(client, fake_redis):
    await _park(fake_redis, source_id="5-0")
    await _park(fake_redis, source_id="5-0")
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert r.text.count(">parked twice</span>") == 2


async def test_entry_fields_are_escaped(client, fake_redis):
    await _park(fake_redis, {"event_type": "<img src=x onerror=alert(1)>", "payload": "{}"})
    r = await client.get(DLQ_URL, headers=_HEADERS)
    assert "<img src=x" not in r.text


async def test_the_dlq_section_pages(client, fake_redis):
    for n in range(3):
        await _park(fake_redis, source_id=f"{n}-0")
    r = await client.get(f"{DLQ_URL}?limit=2", headers=_HEADERS)
    assert r.text.count("data-entry-id=") == 2
    assert f"{DLQ_URL}?offset=2&amp;limit=2" in r.text


# ---------------------------------------------------------------------------
# DLQ actions
# ---------------------------------------------------------------------------


async def test_discard_deletes_the_entry(client, fake_redis):
    entry = await _park(fake_redis)

    r = await client.post(f"{DLQ_URL}/{entry}/discard", headers=_HEADERS)

    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert not _entry_present(r.text, entry)
    assert await fake_redis.xlen(DLQ) == 0


async def test_a_foreign_entry_can_still_be_discarded(client, fake_redis):
    """D4: discard follows the API's documented role decision; the confirm warns."""
    entry = await _park(fake_redis, group="replicator.revisions")
    r = await client.post(f"{DLQ_URL}/{entry}/discard", headers=_HEADERS)
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert await fake_redis.xlen(DLQ) == 0


async def test_discarding_a_gone_entry_is_a_warning(client, fake_redis):
    r = await client.post(f"{DLQ_URL}/1-0/discard", headers=_HEADERS)
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "warning"


@pytest.mark.parametrize("action", ["discard", "reprocess"])
@pytest.mark.parametrize("entry_id", ["-", "1727179200000", f"{2**64}-0"])
async def test_an_inexact_entry_id_is_a_flash_and_touches_nothing(
    client, fake_redis, db_factory, action, entry_id
):
    await _park(fake_redis)
    r = await client.post(f"{DLQ_URL}/{entry_id}/{action}", headers=_HEADERS)
    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "error"
    assert await fake_redis.xlen(DLQ) == 1


@pytest.mark.parametrize("action", ["discard", "reprocess"])
async def test_a_dlq_action_bus_dormant_is_a_flash(client, dormant, db_factory, action):
    r = await client.post(f"{DLQ_URL}/1-0/{action}", headers=_HEADERS)
    assert r.status_code == 200
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "error"
    assert "dormant" in flash["body"]


async def test_a_broker_failure_mid_discard_reports_the_id_in_doubt(client, fake_redis):
    entry = await _park(fake_redis)

    async def fail(*_a):
        raise RedisConnectionError("broker went away")

    with patch.object(fake_redis, "xdel", fail):
        r = await client.post(f"{DLQ_URL}/{entry}/discard", headers=_HEADERS)

    assert r.status_code == 200
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "error"
    assert entry in flash["body"]
    assert "re-list" in flash["body"].lower()


async def test_reprocess_runs_the_handler_and_removes_what_it_settled(
    client, fake_redis, db_factory
):
    """An observation for an InfoSource the registry does not hold is the handler's
    ack-and-drop: settled, so the entry goes."""
    entry = await _park(fake_redis, _observed_wire(str(ULID())), source_id="1-0")

    r = await client.post(f"{DLQ_URL}/{entry}/reprocess", headers=_HEADERS)

    assert r.status_code == 200
    assert read_flash(r)["showFlash"]["level"] == "success"
    assert await fake_redis.xlen(DLQ) == 0
    assert not _entry_present(r.text, entry)


async def test_reprocessing_poison_is_rejected_and_stays(client, fake_redis, db_factory):
    entry = await _park(
        fake_redis, _observed_wire(str(ULID()), fingerprint="deadbeef"), source_id="2-0"
    )

    r = await client.post(f"{DLQ_URL}/{entry}/reprocess", headers=_HEADERS)

    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "error"
    assert "InvalidFingerprintError" in flash["body"]
    assert _entry_present(r.text, entry)


async def test_reprocessing_a_foreign_entry_by_url_is_not_owned(client, fake_redis, db_factory):
    """The button is not rendered, but the route is still the core's guard."""
    entry = await _park(fake_redis, _observed_wire(str(ULID())), group="replicator.revisions")
    r = await client.post(f"{DLQ_URL}/{entry}/reprocess", headers=_HEADERS)
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "warning"
    assert "replicator.revisions" in flash["body"]
    assert await fake_redis.xlen(DLQ) == 1


async def test_a_broker_failure_mid_reprocess_reports_progress(client, fake_redis, db_factory):
    entry = await _park(fake_redis, _observed_wire(str(ULID())), source_id="1-0")

    async def fail(*_a):
        raise RedisConnectionError("broker went away")

    with patch.object(fake_redis, "xdel", fail):
        r = await client.post(f"{DLQ_URL}/{entry}/reprocess", headers=_HEADERS)

    assert r.status_code == 200
    flash = read_flash(r)["showFlash"]
    assert flash["level"] == "error"
    assert entry in flash["body"]
    assert "in doubt" in flash["body"]


# ---------------------------------------------------------------------------
# Audit (D5)
# ---------------------------------------------------------------------------


async def _user_id(session) -> str:
    user = (
        await session.execute(select(AppUser).where(AppUser.external_id == "ext-triage"))
    ).scalar_one()
    return str(user.id)


def _audit_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "Dashboard bus triage action"]


async def test_an_outbox_action_logs_who_asked(client, session, caplog):
    row = await _dead_lettered(session)
    caplog.set_level(logging.INFO)

    await client.post(f"{OUTBOX}/{row.id}/discard", headers=_HEADERS)

    [record] = _audit_records(caplog)
    assert record.app_user_id == await _user_id(session)
    assert record.action == "discard"
    assert record.queue == "changes_outbox"
    assert record.ids == [str(row.id)]
    assert record.outcome == "discarded"
    assert "triage@example.com" not in str(record.__dict__)


async def test_a_dlq_action_logs_who_asked_even_when_interrupted(client, fake_redis, caplog):
    entry = await _park(fake_redis)
    caplog.set_level(logging.INFO)

    async def fail(*_a):
        raise RedisConnectionError("broker went away")

    with patch.object(fake_redis, "xdel", fail):
        await client.post(f"{DLQ_URL}/{entry}/discard", headers=_HEADERS)

    [record] = _audit_records(caplog)
    assert record.queue == DLQ
    assert record.ids == [entry]
    assert record.outcome == "interrupted"


async def test_a_refused_request_logs_no_action(client, caplog):
    """A malformed id reaches no core function, so there is nothing to audit."""
    caplog.set_level(logging.INFO)
    await client.post(f"{OUTBOX}/not-a-ulid/discard", headers=_HEADERS)
    assert _audit_records(caplog) == []
