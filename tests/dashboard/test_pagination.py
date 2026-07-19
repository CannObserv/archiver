"""Tests for dashboard pagination clamping (#84).

Two layers:

* Unit tests over ``pagination()`` — the boundary matrix lives here, since that
  is where the clamp logic actually is.
* One HTTP test per paginated route — guards the *wiring* (that each route
  routes its params through the dependency), not the clamp arithmetic.
"""

from __future__ import annotations

import pytest

from src.api.main import app
from src.core.models.domain import Domain
from src.dashboard.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp

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
    assert clamp(limit=raw, offset=0).limit == expected


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
    assert clamp(limit=DEFAULT_LIMIT, offset=raw).offset == expected


def test_in_range_values_pass_through():
    page = clamp(limit=DEFAULT_LIMIT, offset=10)
    assert (page.limit, page.offset) == (DEFAULT_LIMIT, 10)


# ---------------------------------------------------------------------------
# OpenAPI: bounds are published even though they are not enforced
# ---------------------------------------------------------------------------


def test_openapi_publishes_bounds():
    """Bounds reach the spec via `json_schema_extra`, not `ge`/`le`.

    `ge`/`le` would re-enable the 422 the clamp exists to avoid, so the schema
    would otherwise advertise unbounded integers while the server clamps.
    """
    params = app.openapi()["paths"]["/dashboard/domains/"]["get"]["parameters"]
    by_name = {p["name"]: p for p in params}

    assert by_name["limit"]["schema"]["minimum"] == 1
    assert by_name["limit"]["schema"]["maximum"] == MAX_LIMIT
    assert by_name["limit"]["schema"]["default"] == DEFAULT_LIMIT
    assert by_name["offset"]["schema"]["minimum"] == 0

    # The description must say "clamped", so the published bounds don't imply a
    # rejection the route will never perform.
    assert "clamped" in by_name["limit"]["description"]
    assert "clamped" in by_name["offset"]["description"]


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
async def test_oversized_limit_actually_bounds_the_query(client, session):
    """The clamp must cap the render, not merely avoid a 500.

    `test_oversized_limit_renders` above would still pass if MAX_LIMIT were
    raised to 100_000 — it only asserts "no error". This one seeds MAX_LIMIT + 1
    rows and asserts the page stops at MAX_LIMIT, which is the issue's second
    stated concern (an unbounded `?limit=` attempting a full-table render).
    """
    names = [f"bulk-{i:04d}.example.com" for i in range(MAX_LIMIT + 1)]
    for name in names:
        session.add(Domain(name=name))
    await session.commit()

    r = await client.get("/dashboard/domains/?limit=100000", headers=_HEADERS)
    assert r.status_code == 200

    # The list orders by name, so the seeded block is contiguous and the
    # (MAX_LIMIT + 1)-th name is the first one to fall off the page.
    rendered = [n for n in names if n in r.text]
    assert len(rendered) == MAX_LIMIT
    assert names[MAX_LIMIT] not in r.text


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
