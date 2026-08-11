"""Shared exception rendering for the bus paths — producer and consumer.

``repr(exc)`` alone loses the diagnosis. co-core's ``BusMessageAnomaly`` wrappers
name only the event_type; the sentence saying *which field* is wrong and how to
fix it lives on the chained pydantic ``ValidationError``. Both bus paths are
places where that string is the entire diagnostic available:

- **Producer** (``publisher._dead_letter``) — the build phase is pure, so there is
  no retry to watch and no stream entry to inspect, and the row is terminal by the
  time anyone looks at ``last_error``.
- **Consumer** (``consumer``) — worse: there is no ``last_error`` column at all, so
  the log line is the *only* record a quarantined message leaves behind.

cannobserv#324 is the worked example. A live ``registry_announcement`` missing
``watch_spec`` reprs as 123 characters of "has a malformed payload", while its
cause names the field *and* the remedy. Extracted here rather than duplicated
because fixing one of two structurally identical call sites reads as intentional
later (CR round 1, finding 1).
"""

__all__ = ["error_text"]


def error_text(exc: BaseException) -> str:
    """Render ``exc`` and its chain as one line.

    The exception's own ``repr`` comes first, so downstream matching on the
    wrapper type name keeps working (``test_build_phase_last_error_names_co_core_anomaly``
    pins that contract). Each chained cause is appended as
    ``caused by <Type>: <message>``.

    Follows ``__cause__`` where present and falls back to ``__context__``
    otherwise, because an exception raised inside an ``except`` block *without*
    ``from`` chains implicitly — and the diagnosis should not depend on an
    upstream style choice (CR round 1, finding 6). ``raise ... from None`` sets
    ``__suppress_context__``, which is an explicit "the context is noise" and is
    honoured. Cyclic chains terminate on an identity check: a hung drain loop
    would be a far worse outcome than a truncated message.
    """
    parts = [repr(exc)]
    seen = {id(exc)}
    current: BaseException | None = exc
    while current is not None:
        nxt = current.__cause__
        if nxt is None and not current.__suppress_context__:
            nxt = current.__context__
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        parts.append(f"caused by {type(nxt).__name__}: {nxt}")
        current = nxt
    return " | ".join(parts)
