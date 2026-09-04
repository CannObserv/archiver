"""How long each bus loop blocks on a read, in one leaf module.

Split out of the consumer modules for a dependency-direction reason (CR round 2,
finding 13). ``bus_client`` must derive its ``socket_timeout`` from the longest
of these windows - a value at or below one of them manufactures a timeout on
every idle read - but importing the consumer modules to read two integers put the
client-construction module *downstream* of the loops that consume its client.

Nothing was broken by that yet, only because ``build_group_consumer`` takes a
client rather than building one. The moment a consumer builds its own - the
obvious next refactor once there is a policy worth applying - the import becomes
a cycle, and an ``ImportError`` at startup is a poor way to discover a layering
mistake. A leaf both sides import cannot cycle.

The consumer modules re-export these as their own ``READ_BLOCK_MS`` so their
call sites and defaults read unchanged, and so the discovery guard in
``tests/core/changes/test_bus_client.py`` still finds them where the loops are.
"""

from __future__ import annotations

# The two group consumers (content.revisions, content.artifacts) share one
# window via src/core/changes/group_consumer.py.
GROUP_READ_BLOCK_MS = 5_000

# The groupless info.watch-status tail. Equal to the group window today and
# owned separately on purpose: they answer to different producers and there is
# no reason they must move together.
WATCH_STATUS_READ_BLOCK_MS = 5_000

# What bus_client derives its socket timeout from. Declared here rather than
# computed at the client, so the client depends on one leaf name instead of on
# every module that happens to block.
LONGEST_READ_BLOCK_MS = max(GROUP_READ_BLOCK_MS, WATCH_STATUS_READ_BLOCK_MS)
