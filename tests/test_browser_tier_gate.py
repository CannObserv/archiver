"""The browser tier is collected only when ``-m`` selects it (archiver#546).

A command-line ``-m`` *replaces* a marker expression in ``addopts`` rather than
intersecting with it, so ``-m 'not browser'`` in ``addopts`` would not survive CI's
``pytest -m "not integration"`` (power-map ran its browser tier by accident that
way, #304). The tier is kept out at collection instead: ``tests/browser/`` imports
Playwright at module scope, and a run that did not ask for it never imports it.
A run that asks for it without the ``browser`` group fails at the conftest's
import, loudly, rather than skipping to green.
"""

from pathlib import Path

import pytest

from tests.conftest import BROWSER_DIR, selects_browser


@pytest.mark.parametrize(
    "markexpr",
    ["browser", "browser and not integration", "integration or browser", "(browser)"],
)
def test_an_expression_selecting_the_tier_collects_it(markexpr: str) -> None:
    assert selects_browser(markexpr)


@pytest.mark.parametrize(
    "markexpr",
    ["", "not integration", "integration", "not browser", "not  browser", "browserish"],
)
def test_any_other_expression_leaves_it_uncollected(markexpr: str) -> None:
    assert not selects_browser(markexpr)


def test_the_gated_directory_is_the_browser_tier() -> None:
    assert BROWSER_DIR == Path(__file__).resolve().parent / "browser"
    assert (BROWSER_DIR / "conftest.py").is_file()


def test_this_run_did_not_collect_it(request: pytest.FixtureRequest) -> None:
    """The default gate (pre-ship, CI's two pytest steps) holds no browser test."""
    if selects_browser(request.config.option.markexpr or ""):
        pytest.skip("this run asked for the browser tier")
    collected = [item for item in request.session.items if BROWSER_DIR in item.path.parents]
    assert collected == []
