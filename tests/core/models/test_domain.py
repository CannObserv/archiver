"""Domain model tests: the fetch-policy columns archiver#360 adds.

``min_interval_seconds`` is NOT NULL with Watcher's default, so every host
carries an explicit policy when #366 publishes. Its CHECK refuses negatives,
infinities and NaN: Postgres sorts ``NaN`` above every number, so ``>= 0``
alone would admit it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.core.models.domain import DEFAULT_MIN_INTERVAL_SECONDS, Domain


@pytest.mark.asyncio
async def test_new_domain_defaults_to_watchers_min_interval_and_no_cadence(session):
    domain = Domain(name="defaults.example.com")
    session.add(domain)
    await session.flush()
    await session.refresh(domain)

    assert DEFAULT_MIN_INTERVAL_SECONDS == 1.0
    assert domain.min_interval_seconds == 1.0
    assert domain.default_watch_spec is None


@pytest.mark.asyncio
async def test_server_default_fills_an_insert_that_omits_the_columns(session):
    """The previous release inserts without them (expand-only, archiver#330 D3)."""
    await session.execute(
        text("INSERT INTO information.domains (id, name) VALUES (:id, 'old.example.com')"),
        {"id": "01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )
    row = (
        await session.execute(
            text(
                "SELECT min_interval_seconds, default_watch_spec FROM information.domains"
                " WHERE name = 'old.example.com'"
            )
        )
    ).one()
    assert row == (1.0, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["-0.5", "'Infinity'", "'NaN'"])
async def test_min_interval_check_refuses_negative_infinite_and_nan(session, bad):
    session.add(Domain(name="bad.example.com"))
    await session.flush()
    with pytest.raises(IntegrityError, match="ck_domains_min_interval_seconds"):
        await session.execute(
            text(
                f"UPDATE information.domains SET min_interval_seconds = {bad}"
                " WHERE name = 'bad.example.com'"
            )
        )


@pytest.mark.asyncio
async def test_zero_min_interval_is_legal(session):
    session.add(Domain(name="zero.example.com", min_interval_seconds=0.0))
    await session.flush()


@pytest.mark.asyncio
async def test_unset_cadence_is_sql_null_not_jsonb_null(session):
    session.add(Domain(name="null.example.com", default_watch_spec=None))
    await session.flush()
    is_sql_null = (
        await session.execute(
            text(
                "SELECT default_watch_spec IS NULL FROM information.domains"
                " WHERE name = 'null.example.com'"
            )
        )
    ).scalar_one()
    assert is_sql_null is True
