"""Generic pagination envelope for list endpoints."""

from pydantic import BaseModel


class Page[ItemT](BaseModel):
    """Envelope returned by paginated list endpoints.

    ``has_more`` is derived via a limit+1 probe at query time — no COUNT(*).
    Server guarantees stable ordering across pages via a unique row-id
    tiebreaker, so offset-based iteration is safe (no row appears twice or
    silently drops between adjacent pages even when ``created_at`` collides).
    """

    items: list[ItemT]
    has_more: bool
    limit: int
    offset: int
