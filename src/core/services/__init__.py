"""Domain services — write paths shared by the HTTP surface and the bus consumers.

A service here owns one registry mutation end to end: validation that is domain
rather than transport, the write itself, and the ``changes_outbox`` row that
announces it. It raises domain errors (never ``HTTPException``) and never
commits — the caller owns the transaction boundary, because "row and outbox event
in one transaction" is the outbox pattern's whole guarantee and only the caller
knows where that transaction ends.
"""
