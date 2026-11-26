"""Fixtures for the browser tier (archiver#546): a loopback server and headless Chromium.

Collected only when ``-m`` selects ``browser`` (``tests/conftest.py``), so this
module's Playwright import runs only then; without the ``browser`` group it fails
here, which is the intent. Run::

    bash scripts/install_browser.sh
    uv run --group browser pytest -m browser

- ``live_server`` (session): the app in a uvicorn subprocess on 127.0.0.1,
  against ``archiver_test`` (``tests/browser/server.py``). It depends on
  ``test_engine``, so it stops before that fixture drops the schema.
- ``browser`` (session): one headless Chromium (the pinned headless shell).
- ``open_page``: a fresh context per call, with the dashboard's ``X-ExeDev-*``
  identity, a viewport, touch, and reduced-motion and color-scheme emulation.

Rows a test commits are its own to delete. The one row the server writes itself,
the ``AppUser`` an authed dashboard GET upserts, ``open_page`` deletes after each
test, so a run mixing tiers never shows it to a later test (CR 5).
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from playwright.async_api import Browser, Page, async_playwright
from sqlalchemy import text

from tests.browser.server import LiveServer, start_server
from tests.conftest import in_browser_tier

#: The identity the exe.dev proxy would inject; the dashboard trusts it (#517).
USER_ID = "browser-tier"
AUTH_HEADERS = {"X-ExeDev-UserID": USER_ID, "X-ExeDev-Email": "browser-tier@example.test"}

#: Playwright's default is 30 s; an element missing on an old tree fails in 5.
TIMEOUT_MS = 5_000

#: #400's two widths: a phone, and the desktop layout.
PHONE = 390
DESKTOP = 1280


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every test under ``tests/browser/`` before ``-m`` deselects by marker."""
    for item in items:
        if in_browser_tier(item.path):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
async def live_server(test_engine) -> AsyncIterator[LiveServer]:
    server = start_server()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
async def browser() -> AsyncIterator[Browser]:
    async with async_playwright() as p:
        chromium = await p.chromium.launch(headless=True)
        try:
            yield chromium
        finally:
            await chromium.close()


OpenPage = Callable[..., Awaitable[Page]]


@pytest.fixture
async def open_page(
    browser: Browser, live_server: LiveServer, test_engine
) -> AsyncIterator[OpenPage]:
    """``await open_page(path, width=..., has_touch=..., reduced_motion=..., color_scheme=...)``."""
    contexts = []

    async def _open(
        path: str = "/dashboard/",
        *,
        width: int = DESKTOP,
        height: int = 800,
        has_touch: bool = False,
        reduced_motion: str = "no-preference",
        color_scheme: str = "light",
    ) -> Page:
        context = await browser.new_context(
            base_url=live_server.base_url,
            viewport={"width": width, "height": height},
            has_touch=has_touch,
            reduced_motion=reduced_motion,
            color_scheme=color_scheme,
            extra_http_headers=AUTH_HEADERS,
        )
        contexts.append(context)
        context.set_default_timeout(TIMEOUT_MS)
        page = await context.new_page()
        response = await page.goto(path)
        assert response is not None and response.ok, f"{path}: {response and response.status}"
        return page

    yield _open
    for context in contexts:
        await context.close()
    async with test_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM information.app_users WHERE external_id = :ext"),
            {"ext": USER_ID},
        )
