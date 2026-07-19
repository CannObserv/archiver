"""Tests for dashboard pagination clamping (#84).

Two layers:

* Unit tests over ``pagination()`` — the boundary matrix lives here, since that
  is where the clamp logic actually is.
* One HTTP test per paginated route — guards the *wiring* (that each route
  routes its params through the dependency), not the clamp arithmetic.
"""

from __future__ import annotations

import pytest

from src.core.models.domain import Domain
from src.dashboard.pagination import DEFAULT_LIMIT, MAX_LIMIT, pagination

_HEADERS = {"X-ExeDev-UserID": "ext-page", "X-ExeDev-Email": "page@example.com"}


# ---------------------------------------------------------------------------
# Unit: clamp boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (-100, 1),
        (-1, 1),
        (0, 1),
        (1, 1),
        (DEFAULT_LIMIT, DEFAULT_LIMIT),
        (MAX_LIMIT, MAX_LIMIT),
        (MAX_LIMIT + 1, MAX_LIMIT),
        (100_000, MAX_LIMIT),
    ],
)
def test_limit_is_clamped(raw: int, expected: int):
    assert pagination(limit=raw).limit == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (-100, 0),
        (-1, 0),
        (0, 0),
        (1, 1),
        (100_000, 100_000),
    ],
)
def test_offset_is_floored_but_not_capped(raw: int, expected: int):
    """Offset has no ceiling — a large offset just yields an empty page."""
    assert pagination(offset=raw).offset == expected


def test_defaults():
    page = pagination()
    assert (page.limit, page.offset) == (DEFAULT_LIMIT, 0)


# ---------------------------------------------------------------------------
# HTTP: every paginated dashboard route survives hostile params
# ---------------------------------------------------------------------------

_PAGINATED_ROUTES = [
    "/dashboard/domains/",
    "/dashboard/info-items/",
    "/dashboard/info-sources/",
    "/dashboard/rep-specs/",
    "/dashboard/source-revisions/",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _PAGINATED_ROUTES)
async def test_negative_params_render_instead_of_500(client, path: str):
    r = await client.get(f"{path}?limit=-5&offset=-1", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _PAGINATED_ROUTES)
async def test_oversized_limit_renders(client, path: str):
    r = await client.get(f"{path}?limit=100000", headers=_HEADERS)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_domain_detail_negative_params_render(client, session):
    """The route that surfaced the bug (#82 CR round 7) — has its own params."""
    session.add(Domain(name="clamp.example.com"))
    await session.commit()

    r = await client.get(
        "/dashboard/domains/clamp.example.com?limit=-5&offset=-1", headers=_HEADERS
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
