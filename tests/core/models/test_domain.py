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


# --- fetch_policy_generation (archiver#366) ---------------------------------


@pytest.mark.asyncio
async def test_every_insert_draws_a_distinct_fetch_policy_generation(session):
    """One sequence for every host: values never repeat, so a re-added host
    cannot land on (or under) a generation an earlier frame already used."""
    session.add_all([Domain(name="gen-a.example.com"), Domain(name="gen-b.example.com")])
    await session.flush()
    rows = (
        await session.execute(
            text(
                "SELECT fetch_policy_generation FROM information.domains"
                " WHERE name IN ('gen-a.example.com', 'gen-b.example.com')"
            )
        )
    ).scalars()
    values = list(rows)
    assert len(values) == 2
    assert all(v is not None and v >= 1 for v in values)
    assert values[0] != values[1]


@pytest.mark.asyncio
async def test_an_insert_omitting_the_generation_takes_the_sequence(session):
    """The previous release inserts without it (expand-only, archiver#330 D3)."""
    await session.execute(
        text("INSERT INTO information.domains (id, name) VALUES (:id, 'oldgen.example.com')"),
        {"id": "01JZZZZZZZZZZZZZZZZZZZZZZY"},
    )
    value = (
        await session.execute(
            text(
                "SELECT fetch_policy_generation FROM information.domains"
                " WHERE name = 'oldgen.example.com'"
            )
        )
    ).scalar_one()
    assert value >= 1


@pytest.mark.asyncio
async def test_fetch_policy_generation_is_not_null(session):
    session.add(Domain(name="nn.example.com"))
    await session.flush()
    with pytest.raises(IntegrityError, match="fetch_policy_generation"):
        await session.execute(
            text(
                "UPDATE information.domains SET fetch_policy_generation = NULL"
                " WHERE name = 'nn.example.com'"
            )
        )
