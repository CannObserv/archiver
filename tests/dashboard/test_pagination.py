"""Tests for dashboard pagination clamping (#84, #86).

Three layers, matching the section headers below:

* **Unit** — the boundary matrix over ``clamp_pagination()``, where both the
  parse and the arithmetic live. Inputs are raw query strings, because that is
  what the dependency now hands over (#86).
* **OpenAPI** — that the published bounds agree with what the clamp enforces.
  The two are decoupled by design (``json_schema_extra`` rather than
  ``ge``/``le``), so nothing but this test stops the spec from drifting.
* **HTTP** — that each paginated route routes its params through the
  dependency, and that the clamp bounds the render rather than merely avoiding
  the 500 that motivated the issue.
"""

from __future__ import annotations

from types import NoneType
from typing import get_args

import pytest
from fastapi.dependencies.utils import get_flat_dependant
from fastapi.routing import APIRoute
from sqlalchemy import select

from src.api.main import app
from src.core.models.domain import Domain
from src.dashboard.pagination import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MAX_OFFSET,
    MIN_OFFSET,
    clamp_pagination,
)

_HEADERS = {"X-ExeDev-UserID": "ext-page", "X-ExeDev-Email": "page@example.com"}


# ---------------------------------------------------------------------------
# Unit: clamp boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-100", 1),
        ("-1", 1),
        ("0", 1),
        ("1", 1),
        (str(DEFAULT_LIMIT), DEFAULT_LIMIT),
        (str(MAX_LIMIT), MAX_LIMIT),
        (str(MAX_LIMIT + 1), MAX_LIMIT),
        ("100000", MAX_LIMIT),
    ],
)
def test_limit_is_clamped(raw: str, expected: int):
    assert clamp_pagination(limit=raw, offset="0").limit == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-100", 0),
        ("-1", 0),
        ("0", 0),
        ("1", 1),
        ("100000", 100_000),
        (str(MAX_OFFSET), MAX_OFFSET),
        (str(MAX_OFFSET + 1), MAX_OFFSET),
        (str(10**30), MAX_OFFSET),
    ],
)
def test_offset_is_floored_and_capped_at_int64(raw: str, expected: int):
    """Offset's ceiling is a storage bound, not a product one.

    A large offset does just yield an empty page — right up until it exceeds
    int64 and asyncpg refuses to bind it to `OFFSET $2::BIGINT`, which surfaced
    as a 500 (CR round 4, finding 1). The cap is the widest value the query can
    actually carry, so it changes no behaviour except replacing that crash.
    """
    assert clamp_pagination(limit=str(DEFAULT_LIMIT), offset=raw).offset == expected


def test_in_range_values_pass_through():
    page = clamp_pagination(limit=str(DEFAULT_LIMIT), offset="10")
    assert (page.limit, page.offset) == (DEFAULT_LIMIT, 10)


# ---------------------------------------------------------------------------
# Unit: unparseable input falls back to the default (#86)
# ---------------------------------------------------------------------------
#
# Taking the params as strings and parsing them here is what closes #86. Under
# `int` annotations FastAPI coerced before the dependency ran, so `?limit=abc`
# raised RequestValidationError and the app-wide handler answered a browser
# with a JSON envelope. There is no HTML error path on the dashboard, so the
# fix is to leave no error to render.


@pytest.mark.parametrize("raw", ["abc", "", " ", "5.5", "1e3", "0x10", "50,", None])
def test_unparseable_limit_falls_back_to_default(raw: str | None):
    assert clamp_pagination(limit=raw, offset="0").limit == DEFAULT_LIMIT


@pytest.mark.parametrize("raw", ["abc", "", " ", "5.5", None])
def test_unparseable_offset_falls_back_to_default(raw: str | None):
    assert clamp_pagination(limit=str(DEFAULT_LIMIT), offset=raw).offset == DEFAULT_OFFSET


def test_surrounding_whitespace_is_tolerated():
    """`int()` accepts padding, and a stray space in a hand-typed URL is not
    worth discarding the value the user clearly meant."""
    assert clamp_pagination(limit=" 25 ", offset=" 10 ") == clamp_pagination(
        limit="25", offset="10"
    )


def test_one_bad_param_does_not_discard_the_other():
    """Each param is parsed independently — a garbage `limit` must not reset a
    perfectly good `offset` (and vice versa)."""
    assert clamp_pagination(limit="abc", offset="30") == clamp_pagination(
        limit=str(DEFAULT_LIMIT), offset="30"
    )


# ---------------------------------------------------------------------------
# Guard: no dashboard route may declare a param FastAPI has to coerce (#86)
# ---------------------------------------------------------------------------


def test_no_dashboard_route_declares_a_coercible_param():
    """Pin the claim that makes the #86 fix total, rather than asserting it in prose.

    Parsing `limit`/`offset` by hand closes the raw-JSON-422 path only while
    they are the last params FastAPI has to coerce. A future route declaring
    `after: date` or `page: int` silently reopens it: coercion happens during
    dependency solving, before any dashboard code runs, so there is nothing to
    clamp and no HTML to render — `src/api/errors.py` answers a browser with a
    JSON envelope. That regression is invisible until someone hand-edits a URL,
    so it needs a tripwire and not a docstring.

    Scalars only: a `str` field can fail validation on *absence*
    (`Form(...)` with nothing posted), but that is a broken template rather than
    user input, and it is not what #86 is about.
    """
    offenders, inspected, routes_seen = [], 0, 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/dashboard"):
            continue
        routes_seen += 1
        flat = get_flat_dependant(route.dependant, skip_repeats=True)
        for field in (*flat.path_params, *flat.query_params, *flat.body_params):
            inspected += 1
            annotation = field.field_info.annotation
            # `str | None` is fine — optionality is absence, not coercion. Strip
            # the None arm and require every remaining member to be `str`.
            members = [a for a in get_args(annotation) if a is not NoneType] or [annotation]
            if any(m is not str for m in members):
                offenders.append(f"{route.path} · {field.name}: {annotation}")

    # Non-vacuity: a guard that silently walks nothing passes forever. Assert
    # both stages of the walk found something rather than picking a threshold —
    # any floor on the param count would be a magic number that neither tracks
    # the dashboard's real size nor says what it is protecting.
    assert routes_seen, "no /dashboard routes matched — the walk is broken, not the routes"
    assert inspected, f"{routes_seen} dashboard routes matched but no params were inspected"

    assert not offenders, (
        "Dashboard params must be `str` and parsed by hand — FastAPI coercion "
        "failures render as JSON, not HTML (#86). Offenders:\n  "
        + "\n  ".join(offenders)
        + "\n\nIf a param genuinely cannot be clamped into something sensible, "
        "the HTML error page sketched in #86 is the answer; see "
        "src/dashboard/pagination.py."
    )


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
    huge, tiny = str(10**6), str(-(10**6))

    assert by_name["limit"]["schema"]["minimum"] == clamp_pagination(limit=tiny, offset="0").limit
    assert by_name["limit"]["schema"]["maximum"] == clamp_pagination(limit=huge, offset="0").limit
    # Published as a *string* default against an integer type — FastAPI reads
    # `default` off the signature and it outranks `json_schema_extra`. Asserting
    # the parsed value rather than the literal, so this pins the default that
    # actually applies without pretending the type mismatch is absent.
    assert int(by_name["limit"]["schema"]["default"]) == DEFAULT_LIMIT
    assert int(by_name["offset"]["schema"]["default"]) == MIN_OFFSET
    assert (
        by_name["offset"]["schema"]["minimum"] == clamp_pagination(limit=None, offset=tiny).offset
    )

    # Published as integers even though the handler now takes the raw string
    # (#86). Consumers should still be told to send an integer; tolerating
    # garbage is a robustness concession, not part of the contract.
    assert by_name["limit"]["schema"]["type"] == "integer"
    assert by_name["offset"]["schema"]["type"] == "integer"

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
@pytest.mark.parametrize("path", _PAGINATED_ROUTES)
async def test_unparseable_params_render_html_not_json(client, path: str):
    """#86: `?limit=abc` used to 422 with a JSON envelope in a browser.

    Asserting the content-type, not just the status — a 200 alone would not
    distinguish this from the negative-value case #84 already handled, and the
    complaint in #86 was specifically about the *shape* of the response.
    """
    r = await client.get(f"{path}?limit=abc&offset=xyz", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _PAGINATED_ROUTES)
async def test_offset_past_int64_renders_instead_of_500(client, path: str):
    """CR round 4, finding 1: `?offset=2**63` reached SQL and crashed.

    asyncpg binds the route's offset to `OFFSET $2::BIGINT` and rejects anything
    wider with `DataError: value out of int64 range`, which the app answered as
    500 `application/json` — the exact pairing (crash + JSON at a browser) that
    #84 and #86 each set out to remove.
    """
    r = await client.get(f"{path}?offset={MAX_OFFSET + 1}", headers=_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


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
