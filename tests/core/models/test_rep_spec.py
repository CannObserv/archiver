"""RepSpec model tests."""

import pytest
from sqlalchemy import select

from src.core.models import RepSpec


def _gcs_doc() -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "default",
        "path_template": "{org.acronym_slug}/{event.year}/{file.label_slug}.{file.ext}",
        "required_fields": ["org.acronym", "event.year", "file.label", "file.ext"],
        "object_options": {"storage_class": "ARCHIVE"},
    }


@pytest.mark.asyncio
async def test_round_trip(session):
    spec = RepSpec(
        provider="gcs",
        name="default",
        schema_version=1,
        document=_gcs_doc(),
    )
    session.add(spec)
    await session.commit()
    await session.refresh(spec)
    assert str(spec.rep_spec_id)
    assert spec.provider == "gcs"
    assert spec.document == _gcs_doc()


@pytest.mark.asyncio
async def test_duplicate_provider_name_allowed(session):
    """No uniqueness constraint on (provider, name) — second insert should succeed."""
    a = RepSpec(provider="gcs", name="default", schema_version=1, document=_gcs_doc())
    b = RepSpec(provider="gcs", name="default", schema_version=1, document=_gcs_doc())
    session.add_all([a, b])
    await session.commit()
    result = await session.execute(
        select(RepSpec).where(RepSpec.provider == "gcs", RepSpec.name == "default")
    )
    assert len(list(result.scalars())) == 2


@pytest.mark.asyncio
async def test_provider_index_exists(session):
    """Smoke: query by provider works (confirms the column is queryable)."""
    spec = RepSpec(provider="ia", name="archive", schema_version=1, document={"provider": "ia"})
    session.add(spec)
    await session.commit()
    result = await session.execute(select(RepSpec).where(RepSpec.provider == "ia"))
    fetched = result.scalar_one()
    assert fetched.provider == "ia"
