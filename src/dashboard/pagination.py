"""Shared pagination params for dashboard routes (#84, #86).

The dashboard clamps unusable values instead of rejecting them, which is a
deliberate divergence from the API layer:

* The API is a contract surface — a client sending ``limit=-5`` has a bug, and
  the ``Query(ge=1, le=500)`` 422 makes it loud. See ``src/api/routes/``.
* The dashboard is a human surface, reached by hand-edited URLs, stale
  bookmarks, and back-button history. It also has no HTML rendering path for
  validation errors: ``RequestValidationError`` falls through to the app-wide
  handler in ``src/api/errors.py``, which always returns JSON. Worse, HTMX does
  not swap non-2xx responses, so a 422 on a partial silently does nothing.

Clamping means there is no error path to render at all. That is why the params
arrive here as **strings**: under ``int`` annotations FastAPI coerced before
this dependency ran, so ``?limit=abc`` raised ``RequestValidationError`` and
answered a browser with a JSON envelope — the whole of #86. Parsing here closes
that path, and since these two are the only non-``str`` request params on any
dashboard route, it closes the last one — a claim
``test_no_dashboard_route_declares_a_coercible_param`` pins, since a future
typed param would silently reopen it. Unparseable input falls back to the
default; out-of-range input clamps to the nearest bound, including at the top
of ``offset``, where the bound is what the ``::BIGINT`` bind can carry rather
than a product judgement.

The published schema stays integer-typed, with bounds supplied via
``json_schema_extra`` rather than ``ge``/``le``, which would re-enable the 422
this module exists to avoid. Consumers should still be told to send an integer
within range — tolerating garbage is a robustness concession to hand-edited
URLs, not part of the contract. The ``description`` spells out that
out-of-range values are clamped, so the spec does not imply a rejection it will
not perform.

One wart follows from that: FastAPI takes ``default`` from the Python signature
and it outranks ``json_schema_extra``, so the published default is the *string*
``"50"`` against a declared integer type. Not worth chasing — these are HTML
routes that appear in the OpenAPI document at all only because nothing sets
``include_in_schema=False`` on the dashboard routers.

If a dashboard route ever needs a typed param that *cannot* be clamped into
something sensible, this trick runs out and the HTML error page proposed in #86
becomes the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 50
MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_OFFSET = 0
MIN_OFFSET = 0

# Offset's ceiling is a storage bound, not a product one: the query binds it to
# `OFFSET $2::BIGINT`, and asyncpg rejects anything wider with `DataError: value
# out of int64 range` — a 500, which is the failure this module exists to
# prevent. Capping here changes no behaviour except replacing that crash, since
# any offset this large already yields an empty page.
MAX_OFFSET = 2**63 - 1

_LIMIT_DESCRIPTION = (
    f"Rows per page. Values outside [{MIN_LIMIT}, {MAX_LIMIT}] are clamped to the "
    f"nearest bound rather than rejected; unparseable values fall back to "
    f"{DEFAULT_LIMIT}."
)
_OFFSET_DESCRIPTION = (
    f"Row offset. Values outside [{MIN_OFFSET}, {MAX_OFFSET}] are clamped to the "
    f"nearest bound rather than rejected; unparseable values fall back to "
    f"{DEFAULT_OFFSET}."
)


@dataclass(frozen=True)
class Pagination:
    """Validated page window. Always safe to pass to ``.limit()``/``.offset()``."""

    limit: int
    offset: int


def _bounded(raw: str | None, default: int, minimum: int, maximum: int | None = None) -> int:
    """Parse one raw query value, falling back to ``default``, then clamp it.

    ``int()`` already tolerates surrounding whitespace, so a stray space in a
    hand-typed URL keeps the value the user meant. Everything else it rejects —
    ``""`` (the absent case), ``"abc"``, ``"5.5"`` — takes the default, as does
    ``None``, which only a direct caller can produce.
    """
    try:
        value = default if raw is None else int(raw)
    except ValueError:
        value = default
    value = max(value, minimum)
    return value if maximum is None else min(value, maximum)


def clamp_pagination(limit: str | None, offset: str | None) -> Pagination:
    """Parse and clamp a raw page window.

    ``limit`` is clamped to ``[MIN_LIMIT, MAX_LIMIT]`` and ``offset`` to
    ``[MIN_OFFSET, MAX_OFFSET]``. Each param is handled independently, so one
    unusable value does not discard the other.

    Split out from ``pagination`` so the parse and the arithmetic are directly
    testable — the dependency itself is ``async`` and carries ``Query``
    defaults, neither of which a unit test wants to reach through. Both this
    function and the ``Query`` declarations below read the same bound
    constants, so the published schema cannot drift from the enforced
    behaviour.
    """
    return Pagination(
        limit=_bounded(limit, DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT),
        offset=_bounded(offset, DEFAULT_OFFSET, MIN_OFFSET, MAX_OFFSET),
    )


async def pagination(
    limit: str = Query(
        default=str(DEFAULT_LIMIT),
        description=_LIMIT_DESCRIPTION,
        json_schema_extra={
            "type": "integer",
            "minimum": MIN_LIMIT,
            "maximum": MAX_LIMIT,
        },
    ),
    offset: str = Query(
        default=str(DEFAULT_OFFSET),
        description=_OFFSET_DESCRIPTION,
        json_schema_extra={
            "type": "integer",
            "minimum": MIN_OFFSET,
            "maximum": MAX_OFFSET,
        },
    ),
) -> Pagination:
    """FastAPI dependency yielding a clamped page window.

    Declared ``async`` so FastAPI resolves it inline on the event loop instead
    of dispatching a ``run_in_threadpool`` hop for two comparisons.
    """
    return clamp_pagination(limit, offset)
