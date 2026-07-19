"""Tests for dashboard pagination clamping (#84).

Three layers, matching the section headers below:

* **Unit** — the boundary matrix over ``clamp_pagination()``, where the
  arithmetic actually lives.
* **OpenAPI** — that the published bounds agree with what the clamp enforces.
  The two are decoupled by design (``json_schema_extra`` rather than
  ``ge``/``le``), so nothing but this test stops the spec from drifting.
* **HTTP** — that each paginated route routes its params through the
  dependency, and that the clamp bounds the render rather than merely avoiding
  the 500 that motivated the issue.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.api.main import app
from src.core.models.domain import Domain
from src.dashboard.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_pagination

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
    assert clamp_pagination(limit=raw, offset=0).limit == expected


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
    assert clamp_pagination(limit=DEFAULT_LIMIT, offset=raw).offset == expected


def test_in_range_values_pass_through():
    page = clamp_pagination(limit=DEFAULT_LIMIT, offset=10)
    assert (page.limit, page.offset) == (DEFAULT_LIMIT, 10)


# ---------------------------------------------------------------------------
# OpenAPI: bounds are published even though they are not enforced
# ---------------------------------------------------------------------------


def test_openapi_bounds_agree_with_the_clamp():
    """The published schema must match what the clamp actually enforces.

    Bounds reach the spec via `json_schema_extra` rather than `ge`/`le`, since
    `ge`/`le` would re-enable the 422 the clamp exists to avoid. That decoupling
    is the risk: the schema could drift into advertising a range the route no
    longer honours. So assert each published bound against the value
    `clamp_pagination` actually produces for an out-of-range input, rather than
    against a constant — restating the constant would only prove the schema
    reads it, not that the arithmetic agrees.
    """
    params = app.openapi()["paths"]["/dashboard/domains/"]["get"]["parameters"]
    by_name = {p["name"]: p for p in params}
    huge, tiny = 10**6, -(10**6)

    assert by_name["limit"]["schema"]["minimum"] == clamp_pagination(limit=tiny, offset=0).limit
    assert by_name["limit"]["schema"]["maximum"] == clamp_pagination(limit=huge, offset=0).limit
    assert by_name["limit"]["schema"]["default"] == DEFAULT_LIMIT
    assert (
        by_name["offset"]["schema"]["minimum"]
        == clamp_pagination(limit=DEFAULT_LIMIT, offset=tiny).offset
    )

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
    for i in range(MAX_LIMIT + 1):
        session.add(Domain(name=f"bulk-{i:04d}.example.com"))
    await session.commit()

    # Derive the expected page from the DB using the route's own ordering
    # (Domain.name ascending) rather than assuming the seeded block is the only
    # data present — that assumption would break confusingly if a session-scoped
    # Domain fixture were ever added.
    ordered = list(
        (await session.execute(select(Domain.name).order_by(Domain.name).limit(MAX_LIMIT + 1)))
        .scalars()
        .all()
    )
    assert len(ordered) == MAX_LIMIT + 1, "seed must overflow one page"
    on_page, first_overflow = ordered[:MAX_LIMIT], ordered[MAX_LIMIT]

    r = await client.get("/dashboard/domains/?limit=100000", headers=_HEADERS)
    assert r.status_code == 200

    missing = [n for n in on_page if n not in r.text]
    assert not missing, f"{len(missing)} expected rows absent, e.g. {missing[:3]}"
    assert first_overflow not in r.text


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
