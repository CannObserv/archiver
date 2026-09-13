"""The checker behind the poll-yields-to-the-click invariant (archiver#220).

Each screen that polls asserts ``poll_sync_violations(...) == []`` against its
own poll fragment. These hold the checker to the markups #220 weighed, so an
empty list means the section is safe rather than that the checker saw nothing.
"""

import pytest

from tests.dashboard.conftest import poll_sync_violations

_FIXED_WRAPPER = 'hx-sync="this:abort" hx-disinherit="hx-sync"'


def _section(wrapper_sync: str = "", action_sync: str = "", *, polling: bool = True) -> str:
    poll = f'hx-get="/s" hx-trigger="every 2s" hx-swap="outerHTML" {wrapper_sync}'
    return (
        f'<div id="s" {poll if polling else ""}><a href="/x">x</a>'
        f'<button hx-post="/r" hx-target="#s" aria-label="Replicate" {action_sync}>R</button></div>'
    )


@pytest.mark.parametrize("action_sync", ['hx-sync="closest #s:drop"', 'hx-sync="#s"'])
def test_the_fixed_markup_passes(action_sync):
    """``drop`` is htmx's default strategy, and a bare id resolves to the same wrapper."""
    assert poll_sync_violations(_section(_FIXED_WRAPPER, action_sync), "s") == []


def test_the_markup_before_220_fails():
    """No ``hx-sync`` anywhere: the button syncs on itself and never sees the poll."""
    violations = poll_sync_violations(_section(), "s")
    assert "#s hx-sync is None: the poll must be 'this:abort'" in violations
    assert "<button> 'Replicate' declares no hx-sync" in violations


def test_a_wrapper_only_sync_fails():
    """The remedy #220 warned against. Inherited, the wrapper's ``this:drop``
    points the button at the wrapper too, and a click mid-poll is dropped."""
    violations = poll_sync_violations(_section('hx-sync="this:drop"'), "s")
    assert "#s hx-sync is 'this:drop': the poll must be 'this:abort'" in violations
    assert "#s must disinherit hx-sync" in violations
    assert "<button> 'Replicate' declares no hx-sync" in violations


@pytest.mark.parametrize("strategy", ["abort", "replace", "queue all"])
def test_an_action_drops_rather_than_anything_else(strategy):
    """``abort`` drops the click mid-poll. Between two actions, ``replace`` loses
    the first one's response and ``queue`` never sends the second."""
    html = _section(_FIXED_WRAPPER, f'hx-sync="closest #s:{strategy}"')
    assert poll_sync_violations(html, "s") == [
        f"<button> 'Replicate' uses '{strategy}', not 'drop'"
    ]


def test_an_action_that_syncs_on_itself_fails():
    html = _section(_FIXED_WRAPPER, 'hx-sync="this:drop"')
    assert poll_sync_violations(html, "s") == ["<button> 'Replicate' syncs on 'this', not #s"]


def test_a_render_that_does_not_poll_cannot_pass():
    """Asserted against an idle render, the check would pass vacuously."""
    assert poll_sync_violations(_section(polling=False), "s") == [
        "#s is not polling in this render, so there is nothing to check"
    ]
