"""``error_text`` — the shared exception renderer for bus-path diagnostics.

Extracted from ``publisher._dead_letter`` (CR round 1, finding 1) because the
consumer had the identical ``repr(exc)`` defect on its two quarantine logs, and
worse: a consumer has no ``last_error`` column, so the log line is the *only*
record a quarantined message leaves behind.
"""

import pytest

from src.core.changes.diagnostics import error_text


def test_names_the_exception_type_first():
    """Downstream ``last_error`` greps match on the wrapper type name."""
    assert error_text(ValueError("boom")).startswith("ValueError(")


def test_follows_an_explicit_cause_chain():
    """``raise X from Y`` — the remedy text usually lives on Y."""
    try:
        try:
            raise ValueError("send {'schema_version': 1} with no interval")
        except ValueError as inner:
            raise RuntimeError("malformed payload") from inner
    except RuntimeError as exc:
        rendered = error_text(exc)

    assert "RuntimeError(" in rendered
    assert "caused by ValueError" in rendered
    assert "no interval" in rendered


def test_follows_an_implicit_context_chain():
    """``raise X`` inside an ``except`` block chains via ``__context__``.

    co-core currently raises with ``from``, so this is latent rather than live —
    but the whole point of the renderer is that the diagnosis not depend on an
    upstream style choice (CR round 1, finding 6).
    """
    try:
        try:
            raise ValueError("the real reason")
        except ValueError:
            raise RuntimeError("wrapper")  # noqa: B904 — the point of the test
    except RuntimeError as exc:
        rendered = error_text(exc)

    assert "caused by ValueError: the real reason" in rendered


def test_respects_suppressed_context():
    """``raise X from None`` means "the context is noise" — honour that."""
    try:
        try:
            raise ValueError("irrelevant")
        except ValueError:
            raise RuntimeError("wrapper") from None
    except RuntimeError as exc:
        rendered = error_text(exc)

    assert "caused by" not in rendered


def test_prefers_cause_over_context_at_each_hop():
    """``__cause__`` wins where both exist — but the walk keeps going.

    The explicit cause is chosen at the first hop; the chain then continues
    through *that* exception's own context. Both appear, in that order, and the
    order is the assertion: the deliberate cause is what an operator reads first.
    """
    try:
        try:
            raise ValueError("context")
        except ValueError:
            try:
                raise KeyError("cause")
            except KeyError as k:
                raise RuntimeError("wrapper") from k
    except RuntimeError as exc:
        rendered = error_text(exc)

    assert rendered.index("caused by KeyError") < rendered.index("caused by ValueError")


def test_terminates_on_a_self_referential_chain():
    """A cyclic chain must not hang the drain loop."""
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a

    rendered = error_text(a)

    assert rendered.count("caused by") <= 2


@pytest.mark.parametrize("exc", [ValueError("plain"), RuntimeError("")])
def test_unchained_exceptions_render_without_a_suffix(exc):
    assert "caused by" not in error_text(exc)
