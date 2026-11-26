"""#400's sidebar drawer in real Chromium: the checks happy-dom could not make.

``tests/js/sidebar-drawer.test.js`` covers the wiring in happy-dom. Two defects
passed all of it and failed only here (archiver#400, #546):

1. **Focus refused mid-transition.** A discrete ``visibility`` transition still
   reads ``hidden`` when the toggle's handler calls ``focus()`` on the first link,
   and Chromium refuses it. ``test_enter_opens_with_focus_on_the_first_link...``
   is red with ``visibility`` back in the open state's transition.
2. **A real tap moves focus first.** ``mousedown`` focuses what is under the
   pointer, the ``focusin`` handler closes the drawer, and the ``click`` then sees
   a closed drawer and acts on the control beneath. ``test_a_dismissing_tap...``
   is red on ``50a3d5b2``, the tree before #400's CR 1.

Every test here is red on ``a7dfc25f`` (no drawer at all); the issue's evidence
is the three red trees and a green ``main``.
"""

import pytest
from playwright.async_api import Page

from tests.browser.conftest import DESKTOP, PHONE, OpenPage

TOGGLE = "[data-sidebar-toggle]"
SIDEBAR = "nav.sidebar"
#: More presses than the page has stops before the content, so a walk sees them all.
TAB_PRESSES = 30


async def _sidebar_links_reached_by_tab(page: Page) -> int:
    """How many distinct sidebar links Tab lands on, walking from the top."""
    await page.evaluate("document.activeElement && document.activeElement.blur()")
    reached: set[str] = set()
    for _ in range(TAB_PRESSES):
        await page.keyboard.press("Tab")
        href = await page.evaluate(
            f"""() => {{
                const a = document.activeElement;
                return a && a.closest('{SIDEBAR}') ? a.getAttribute('href') : null;
            }}"""
        )
        if href:
            reached.add(href)
    return len(reached)


async def _page_overflow(page: Page) -> int:
    return await page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


async def _expanded(page: Page) -> str | None:
    return await page.locator(TOGGLE).get_attribute("aria-expanded")


async def _focus_is_first_link(page: Page) -> bool:
    return await page.evaluate(
        f"document.activeElement === document.querySelector('{SIDEBAR} a[href]')"
    )


async def _focus_is_toggle(page: Page) -> bool:
    return await page.evaluate(f"document.activeElement === document.querySelector('{TOGGLE}')")


async def _wait_closed(page: Page) -> None:
    """The closed state after its 150 ms ``visibility`` transition has run."""
    await page.wait_for_function(
        f"getComputedStyle(document.querySelector('{SIDEBAR}')).visibility === 'hidden'"
    )


async def test_phone_width_hides_the_sidebar_out_of_the_tab_order(open_page: OpenPage) -> None:
    page = await open_page("/dashboard/info-items/", width=PHONE)
    sidebar = page.locator(SIDEBAR)
    assert await sidebar.evaluate("e => getComputedStyle(e).visibility") == "hidden"
    box = await sidebar.bounding_box()
    assert box is None or box["x"] + box["width"] <= 0, box
    assert await _sidebar_links_reached_by_tab(page) == 0
    assert await page.locator(TOGGLE).is_visible()
    assert await _page_overflow(page) == 0


async def test_desktop_width_keeps_the_sidebar_and_hides_the_toggle(open_page: OpenPage) -> None:
    page = await open_page("/dashboard/info-items/", width=DESKTOP)
    sidebar = page.locator(SIDEBAR)
    assert await sidebar.is_visible()
    box = await sidebar.bounding_box()
    assert box is not None and box["x"] == 0
    links = await sidebar.locator("a[href]").count()
    assert links > 0
    assert await _sidebar_links_reached_by_tab(page) == links
    assert not await page.locator(TOGGLE).is_visible()
    assert await _page_overflow(page) == 0


async def test_enter_opens_with_focus_on_the_first_link_and_escape_returns_it(
    open_page: OpenPage,
) -> None:
    """Defect 1. Read straight after the key press: the focus() is synchronous."""
    page = await open_page(width=PHONE)
    await page.locator(TOGGLE).focus()

    await page.keyboard.press("Enter")
    assert await _expanded(page) == "true"
    assert await _focus_is_first_link(page), "Chromium refused focus() on the drawer's first link"

    await page.keyboard.press("Tab")
    assert await page.evaluate(f"Boolean(document.activeElement.closest('{SIDEBAR}'))")

    await page.keyboard.press("Escape")
    assert await _expanded(page) == "false"
    assert await _focus_is_toggle(page)

    await page.keyboard.press("Space")
    assert await _expanded(page) == "true"
    assert await _focus_is_first_link(page)


@pytest.mark.parametrize("pointer", ["mouse", "touch"])
async def test_a_dismissing_tap_does_not_act_on_what_is_beneath(
    open_page: OpenPage, pointer: str
) -> None:
    """Defect 2: the tap that closes the drawer must not also press "New Item"."""
    touch = pointer == "touch"
    page = await open_page("/dashboard/info-items/", width=PHONE, has_touch=touch)
    start_url = page.url
    toggle = page.locator(TOGGLE)
    await (toggle.tap() if touch else toggle.click())
    assert await _expanded(page) == "true"

    target = page.get_by_role("link", name="New Item")
    box = await target.bounding_box()
    drawer = await page.locator(SIDEBAR).bounding_box()
    assert box is not None and drawer is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    assert x > drawer["x"] + drawer["width"], "the target must be beside the drawer, not under it"

    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))

    async def press() -> None:
        if touch:
            await page.touchscreen.tap(x, y)
        else:
            await page.mouse.click(x, y)

    await press()
    # htmx issues a boosted request from the click handler itself, so one that
    # was going to happen has happened by the next frame; this is margin.
    await page.wait_for_timeout(500)
    assert [u for u in requests if u.endswith("/info-items/new")] == []
    assert page.url == start_url
    assert await _expanded(page) == "false"

    await press()  # the drawer is closed now: this one is a plain press of New Item
    await page.wait_for_url(lambda url: url != start_url)


async def test_a_boosted_navigation_lands_closed_and_the_toggle_still_works(
    open_page: OpenPage,
) -> None:
    page = await open_page("/dashboard/", width=PHONE)
    await page.evaluate("window.__beforeNavigation = true")
    await page.locator(TOGGLE).click()
    assert await _expanded(page) == "true"

    await page.locator(f"{SIDEBAR} a[href='/dashboard/info-items/']").click()
    await page.wait_for_url("**/dashboard/info-items/")
    assert await page.evaluate("window.__beforeNavigation === true"), "not a boosted swap"

    assert await _expanded(page) == "false"
    assert await page.locator(SIDEBAR).get_attribute("data-open") is None
    await _wait_closed(page)

    await page.locator(TOGGLE).click()
    assert await _expanded(page) == "true"
    assert await _focus_is_first_link(page)
