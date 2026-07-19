"""Shared pagination params for dashboard routes (#84).

The dashboard clamps out-of-range values instead of rejecting them, which is a
deliberate divergence from the API layer:

* The API is a contract surface — a client sending ``limit=-5`` has a bug, and
  the ``Query(ge=1, le=500)`` 422 makes it loud. See ``src/api/routes/``.
* The dashboard is a human surface, reached by hand-edited URLs, stale
  bookmarks, and back-button history. It also has no HTML rendering path for
  validation errors: ``RequestValidationError`` falls through to the app-wide
  handler in ``src/api/errors.py``, which always returns JSON. Worse, HTMX does
  not swap non-2xx responses, so a 422 on a partial silently does nothing.

Clamping means there is no error path to render at all. Note this does not
eliminate 422s entirely — ``?limit=abc`` still fails int coercion before this
dependency runs — but it removes the plausible triggers.

Bounds are published to OpenAPI via ``json_schema_extra`` rather than ``ge``/
``le``, which would re-enable the 422 this module exists to avoid. The
``description`` spells out that out-of-range values are clamped, so the spec
does not imply rejection it will not perform.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 50
MIN_LIMIT = 1
MAX_LIMIT = 200
MIN_OFFSET = 0

_LIMIT_DESCRIPTION = (
    f"Rows per page. Values outside [{MIN_LIMIT}, {MAX_LIMIT}] are clamped to the "
    "nearest bound rather than rejected."
)
_OFFSET_DESCRIPTION = f"Row offset. Values below {MIN_OFFSET} are clamped rather than rejected."


@dataclass(frozen=True)
class Pagination:
    """Validated page window. Always safe to pass to ``.limit()``/``.offset()``."""

    limit: int
    offset: int


def clamp_pagination(limit: int, offset: int) -> Pagination:
    """Clamp a raw page window into range.

    ``limit`` is clamped to ``[MIN_LIMIT, MAX_LIMIT]``; ``offset`` is floored at
    ``MIN_OFFSET`` with no ceiling, since a large offset simply yields an empty
    page.

    Split out from ``pagination`` so the arithmetic is directly testable — the
    dependency itself is ``async`` and carries ``Query`` defaults, neither of
    which a unit test wants to reach through. Both this function and the
    ``Query`` declarations below read the same bound constants, so the published
    schema cannot drift from the enforced behaviour.
    """
    return Pagination(
        limit=min(max(limit, MIN_LIMIT), MAX_LIMIT),
        offset=max(offset, MIN_OFFSET),
    )


async def pagination(
    limit: int = Query(
        default=DEFAULT_LIMIT,
        description=_LIMIT_DESCRIPTION,
        json_schema_extra={"minimum": MIN_LIMIT, "maximum": MAX_LIMIT},
    ),
    offset: int = Query(
        default=MIN_OFFSET,
        description=_OFFSET_DESCRIPTION,
        json_schema_extra={"minimum": MIN_OFFSET},
    ),
) -> Pagination:
    """FastAPI dependency yielding a clamped page window.

    Declared ``async`` so FastAPI resolves it inline on the event loop instead
    of dispatching a ``run_in_threadpool`` hop for two comparisons.
    """
    return clamp_pagination(limit, offset)
