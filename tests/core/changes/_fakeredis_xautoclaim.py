"""Give fakeredis's ``XAUTOCLAIM`` the cursor a Redis 7 server returns (archiver#259).

fakeredis (2.35.1 as locked, and 2.37.0 per cannobserv#465) replies with the
highest *claimed* id as the cursor, never the next id to scan and never ``0-0``.
Because ``start_id`` is inclusive, a walk that follows that cursor claims its
last entry again on every call and never sees the end. So a fakeredis-backed test
of the quarantine scan would pass while running all ``MAX_QUARANTINE_PASSES``
passes.

This rewrites only the cursor: the first pending id after the last claimed one,
or ``0-0`` when none remains. fakeredis has no ``count * 10`` attempt budget, so
the empty-page-with-cursor case cannot be reproduced here; that case is pinned
against scripted pages in ``test_group_consumer``.
"""

from __future__ import annotations

from typing import Any


def _as_text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def with_redis_cursor(client: Any) -> Any:
    """Patch ``client.xautoclaim`` in place so its cursor follows Redis 7 semantics."""
    original = client.xautoclaim

    async def xautoclaim(name, groupname, consumername, min_idle_time, *args, **kwargs):
        _cursor, entries, deleted = await original(
            name, groupname, consumername, min_idle_time, *args, **kwargs
        )
        cursor = "0-0"
        if entries:
            last = _as_text(entries[-1][0])
            after = await client.xpending_range(name, groupname, min=f"({last}", max="+", count=1)
            if after:
                cursor = _as_text(after[0]["message_id"])
        return [cursor, entries, deleted]

    client.xautoclaim = xautoclaim
    return client
