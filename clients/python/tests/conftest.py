"""Test fixtures for archiver-client."""

import pytest
from archiver_client import ArchiverClient

BASE_URL = "http://archiver.test"
API_KEY = "test-key"


@pytest.fixture
async def client():
    async with ArchiverClient(base_url=BASE_URL, api_key=API_KEY, cache_ttl_seconds=60.0) as c:
        yield c
