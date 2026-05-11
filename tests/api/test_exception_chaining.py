"""Verify route handlers preserve `__cause__` when translating internal errors.

These tests cover the contract enforced by ruff B904 (and tracked under #12):
every `except X: raise HTTPException(...) from e` site keeps the original
cause attached to the HTTPException, so the JSON logger can render the inner
traceback.

Route functions are invoked directly (not via TestClient) so the raised
HTTPException is observable before FastAPI's response serializer drops the
chain.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.info_items import deactivate_rep_spec_assignment
from src.api.routes.info_sources import create_info_source_route
from src.api.schemas.info_source import InfoSourceCreate
from src.core.tools.create_info_source import InvalidSourceSpecError


@pytest.mark.asyncio
async def test_malformed_ulid_chains_value_error(session: AsyncSession):
    """Bare `except ValueError as e` sites must keep the ValueError as __cause__."""
    with pytest.raises(HTTPException) as exc_info:
        await deactivate_rep_spec_assignment(
            info_item_id="01HXXXXXXXXXXXXXXXXXXXXXXX",
            assignment_id="not-a-ulid",
            session=session,
        )
    assert exc_info.value.status_code == 422
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_invalid_source_spec_chains_typed_error(session: AsyncSession):
    """`except InvalidSourceSpecError as e` site must keep the typed error as __cause__."""
    body = InfoSourceCreate(source_spec={"not": "a valid source_spec"})
    with pytest.raises(HTTPException) as exc_info:
        await create_info_source_route(body=body, session=session)
    assert exc_info.value.status_code == 422
    assert isinstance(exc_info.value.__cause__, InvalidSourceSpecError)
