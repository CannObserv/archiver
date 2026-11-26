"""#484's overflow check in real Chromium: a long selector chip never sets the page width.

Before #484, register step 2 put the suggestions and the spec editor in a
``1fr 1fr`` grid, and a ``.btn`` chip is ``white-space: nowrap``: the longest chip
set the grid's minimum, and the editor started past the viewport (x=1219 at
1280 px; ``.main-content`` overflowed by 631 px at 768). Measured with the issue's
own chip, a ~150-character ``governor.wa.gov`` xpath that two sources share (``×2``).
Red on ``7cac5ee0``, the tree just before #484's fix.

Nothing is fetched: the suggestions come from the registry, so two committed
sources on the domain are the whole seed, deleted afterwards.
"""

from collections.abc import AsyncIterator

import pytest
from playwright.async_api import Locator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.models import InfoSource
from tests.browser.conftest import DESKTOP, OpenPage

HOST = "governor.wa.gov"
XPATH = (
    "//div[@id='block-drupalbase-custom-views-block-news-news-releases']"
    "//div[contains(concat(' ',normalize-space(@class),' '),' view-content ')]"
)
TABLET = 768


@pytest.fixture
async def long_chip_sources(test_engine) -> AsyncIterator[None]:
    """Two committed sources on ``HOST`` sharing the long xpath spec, so its chip reads ``×2``."""
    spec = [{"schema_version": 1, "extraction": {"algorithm": "xpath", "selector": XPATH}}]
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as s:
        sources = [
            InfoSource(url=f"https://{HOST}/news/{n}", source_specs=spec, domain_name=HOST)
            for n in (1, 2)
        ]
        s.add_all(sources)
        await s.commit()
        ids = [src.info_source_id for src in sources]
    try:
        yield
    finally:
        async with factory() as s:
            await s.execute(delete(InfoSource).where(InfoSource.info_source_id.in_(ids)))
            await s.commit()


async def _right_edge(locator: Locator) -> float:
    box = await locator.bounding_box()
    assert box is not None, f"{locator} has no box"
    return box["x"] + box["width"]


@pytest.mark.parametrize("width", [DESKTOP, TABLET])
async def test_a_long_chip_does_not_push_step_2_off_the_page(
    open_page: OpenPage, long_chip_sources: None, width: int
) -> None:
    page = await open_page("/dashboard/register", width=width)
    await page.locator("#reg-url").fill(f"https://{HOST}/news/new-page")
    await page.get_by_role("button", name="Next: Choose Selector →").click()
    # By role and text, not .selector-chip: #484 added that class, and the tree
    # before it must fail on the overflow, not on a missing class.
    chip = page.get_by_role("button", name="xpath: //div")
    count = chip.locator("span", has_text="×2")
    await count.wait_for()

    assert (
        await page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        == 0
    )
    assert (
        await page.evaluate(
            "(m => m.scrollWidth - m.clientWidth)(document.querySelector('.main-content'))"
        )
        == 0
    )
    assert await _right_edge(count) <= width, "the chip's ×2 is off the page"
    assert await _right_edge(page.locator("textarea").first) <= width, "the editor is off the page"
