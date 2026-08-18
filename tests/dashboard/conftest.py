"""Shared fixtures and helpers for dashboard tests."""

import json

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
