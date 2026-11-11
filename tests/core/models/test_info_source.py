"""InfoSource model tests."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoSource


def _spec(algorithm: str = "full_page", selector: str | None = None) -> dict:
    doc: dict = {
        "schema_version": 1,
        "extraction": {"algorithm": algorithm},
        "fingerprint": {},
    }
    if selector is not None:
        doc["extraction"]["selector"] = selector
    return doc


@pytest.mark.asyncio
async def test_info_source_round_trip(session):
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.commit()
    await session.refresh(src)
    assert str(src.info_source_id)
    assert src.url == "https://example.com/p"
    assert src.source_specs == [_spec()]


@pytest.mark.asyncio
async def test_multiple_specs_persisted(session):
    specs = [_spec("full_page"), _spec("css", "#title")]
    src = InfoSource(url="https://example.com/p", source_specs=specs)
    session.add(src)
    await session.commit()
    await session.refresh(src)
    assert src.source_specs == specs


@pytest.mark.asyncio
async def test_url_not_unique_allows_duplicates(session):
    """Multiple InfoSources can share the same URL (different extraction strategies)."""
    a = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    b = InfoSource(url="https://example.com/p", source_specs=[_spec("css", "#count")])
    session.add_all([a, b])
    await session.commit()  # must not raise


@pytest.mark.asyncio
async def test_url_required(session):
    bad = InfoSource(url=None, source_specs=[_spec()])
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_capture_policy_defaults_to_none_and_round_trips(session):
    """``NULL`` is "no policy": defaults on demand, no revision captures (#380 C)."""
    src = InfoSource(url="https://example.com/p", source_specs=[_spec()])
    session.add(src)
    await session.flush()
    assert src.capture_policy is None

    policy = {
        "viewport": {"width": 390, "height": 844},
        "full_page": False,
        "wait": {"kind": "delay", "selector": None, "seconds": 2.5},
        "on_revision": True,
    }
    src.capture_policy = policy
    source_id = src.info_source_id
    await session.commit()
    session.expire_all()
    got = await session.get(InfoSource, source_id)
    assert got.capture_policy == policy


@pytest.mark.asyncio
async def test_clearing_capture_policy_stores_sql_null(session):
    """``= None`` must be SQL NULL, not JSON ``null`` - "no policy" is a NULL test."""
    src = InfoSource(
        url="https://example.com/p", source_specs=[_spec()], capture_policy={"on_revision": True}
    )
    session.add(src)
    await session.flush()
    src.capture_policy = None
    await session.flush()
    is_null = await session.scalar(
        select(InfoSource.capture_policy.is_(None)).where(
            InfoSource.info_source_id == src.info_source_id
        )
    )
    assert is_null is True
