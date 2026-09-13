"""Shared fixtures and helpers for dashboard tests."""

import json
from html.parser import HTMLParser

import pytest

from src.api.deps import get_redis_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource

_ANNOUNCEABLE_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "full_page"}}]


def read_flash(response) -> dict:
    """The parsed ``HX-Trigger`` header of a dashboard mutation.

    One copy, because it is the reader's entry point to the convention the
    manual-replication routes rest on: htmx discards a 4xx body, so an outcome
    that has to reach the operator rides this header rather than a status code
    (docs/STYLE.md, archiver#171 CR #36/#44).
    """
    return json.loads(response.headers["HX-Trigger"])


_HX_VERBS = ("hx-get", "hx-post", "hx-put", "hx-patch", "hx-delete")


class _SectionAttrs(HTMLParser):
    """The wrapper's attributes, and those of every request-issuing element after it."""

    def __init__(self, wrapper_id: str):
        super().__init__()
        self.wrapper_id = wrapper_id
        self.wrapper: dict | None = None
        self.actions: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.wrapper is None:
            if a.get("id") == self.wrapper_id:
                self.wrapper = a
        elif any(verb in a for verb in _HX_VERBS):
            self.actions.append((tag, a))


def poll_sync_violations(fragment: str, wrapper_id: str) -> list[str]:
    """Every way a self-polling section's poll could beat a click (archiver#220).

    The poll and the row actions swap the same wrapper, so whichever response
    lands second finds its target detached and htmx discards it - swap, focus
    script and ``HX-Trigger`` toast alike. The poll must be the one discarded, so:

    - the wrapper declares ``hx-sync="this:abort"``: its poll is abortable, and
      a tick while an action is in flight is dropped;
    - the wrapper disinherits ``hx-sync``, or every element inside it inherits
      ``this:abort`` - boosted links included - and is dropped mid-poll;
    - each action syncs on the wrapper with ``drop``. ``abort`` would drop the
      click; ``replace`` aborts an in-flight action, losing its response though
      the server commits it; ``queue`` parks the next action on the wrapper,
      where the first action's swap wipes it. No ``hx-sync`` at all syncs on
      the button itself, which never sees the poll.

    ``fragment`` must be the section alone - its poll route's response - so
    every element after the wrapper's start tag is inside it.
    """
    parsed = _SectionAttrs(wrapper_id)
    parsed.feed(fragment)
    wrapper = parsed.wrapper
    if wrapper is None or not (wrapper.get("hx-trigger") or "").startswith("every "):
        return [f"#{wrapper_id} is not polling in this render, so there is nothing to check"]
    violations = []
    if wrapper.get("hx-sync") != "this:abort":
        violations.append(
            f"#{wrapper_id} hx-sync is {wrapper.get('hx-sync')!r}: the poll must be 'this:abort'"
        )
    disinherited = (wrapper.get("hx-disinherit") or "").split()
    if "*" not in disinherited and "hx-sync" not in disinherited:
        violations.append(f"#{wrapper_id} must disinherit hx-sync")
    if not parsed.actions:
        violations.append(f"no request-issuing element inside #{wrapper_id}: a vacuous pass")
    for tag, a in parsed.actions:
        label = a.get("aria-label") or next(a[v] for v in _HX_VERBS if v in a)
        sync = a.get("hx-sync")
        if sync is None:
            violations.append(f"<{tag}> {label!r} declares no hx-sync")
            continue
        selector, _, strategy = sync.partition(":")
        if selector.strip() not in (f"closest #{wrapper_id}", f"#{wrapper_id}"):
            violations.append(f"<{tag}> {label!r} syncs on {selector!r}, not #{wrapper_id}")
        if (strategy.strip() or "drop") != "drop":
            violations.append(f"<{tag}> {label!r} uses {strategy.strip()!r}, not 'drop'")
    return violations


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    """Remove any dependency overrides set during a test."""
    yield
    app.dependency_overrides.pop(get_redis_client, None)


@pytest.fixture
def bind_source():
    """Give an InfoItem an **announceable** primary source.

    Needed by any test that asserts the pause/resume or cadence affordance, and
    since archiver#142 by any test that asserts the panel is in a *watched* state
    at all: announceability — an active binding whose source carries non-empty
    ``source_specs`` — is both the affordance gate (CR round 1 finding 3, round 2
    finding 9) and the state key. An unbound item now renders ``not_watching`` by
    definition, so a fixture without this asserts against the wrong state rather
    than merely a missing button.

    ``specs=[]`` builds the *unannounceable* counterpart: bound, but with
    nothing to reconcile against, which is the other half of the gate.
    """

    async def _bind(session, item: InfoItem, *, slug: str, specs: list | None = None) -> InfoSource:
        src = InfoSource(
            url=f"https://example.test/{slug}",
            source_specs=_ANNOUNCEABLE_SPECS if specs is None else specs,
        )
        session.add(src)
        await session.flush()
        session.add(
            InfoItemSource(info_item_id=item.info_item_id, info_source_id=src.info_source_id)
        )
        await session.flush()
        return src

    return _bind
