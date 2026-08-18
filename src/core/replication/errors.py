"""One base for every reason a replication destination cannot be produced.

The issuance path (archiver#169) records "this assignment could not be
replicated" as a skip with a reason, and it needs a single class to catch. Two
hierarchies — one for a malformed template, one for an unrenderable bag — would
mean an escaped exception in the ``content.revisions`` consumer's loop, where a
single bad RepSpec document would take down the ingest task rather than skipping
one assignment (CR #4).

The distinction the two branches still carry is *who can fix it*: a malformed
template means the create/update gate was bypassed (a bug here), while an
unrenderable bag means an author has editing to do. That belongs in the message
and the log, not in the class a caller has to enumerate.
"""

from __future__ import annotations


class ReplicationRenderError(Exception):
    """A ``content.replicate`` destination could not be produced."""
