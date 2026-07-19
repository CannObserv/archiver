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
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class Pagination:
    """Validated page window. Always safe to pass to ``.limit()``/``.offset()``."""

    limit: int
    offset: int


def pagination(limit: int = DEFAULT_LIMIT, offset: int = 0) -> Pagination:
    """FastAPI dependency yielding a clamped page window.

    ``limit`` is clamped to ``[1, MAX_LIMIT]``; ``offset`` is floored at 0 with
    no ceiling, since a large offset simply yields an empty page.
    """
    return Pagination(limit=min(max(limit, 1), MAX_LIMIT), offset=max(offset, 0))
