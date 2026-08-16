"""Shared fixtures for dashboard tests."""

import pytest

from src.api.deps import get_redis_client, get_watcher_client
from src.api.main import app
from src.core.models import InfoItem, InfoItemSource, InfoSource

_ANNOUNCEABLE_SPECS = [{"schema_version": 1, "extraction": {"algorithm": "full_page"}}]


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    """Remove any dependency overrides set during a test."""
    yield
    for dep in (get_watcher_client, get_redis_client):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def bind_source():
    """Give an InfoItem an **announceable** primary source.

    Needed by any test that asserts the pause/resume or cadence affordance: both
    are gated on announceability — an active binding whose source carries
    non-empty ``source_specs`` — rather than on the Watcher link, because the
    link outlives the binding (CR round 1 finding 3, round 2 finding 9). A
    watched item with no bound source is not a state provisioning can produce,
    so a fixture without this is asserting against a shape the app never emits.

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
