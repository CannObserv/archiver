"""Shared fixtures for dashboard tests."""

import pytest

from src.api.deps import get_redis_client, get_watcher_client
from src.api.main import app


@pytest.fixture(autouse=True)
def _clear_dep_overrides():
    """Remove any dependency overrides set during a test."""
    yield
    for dep in (get_watcher_client, get_redis_client):
        app.dependency_overrides.pop(dep, None)
