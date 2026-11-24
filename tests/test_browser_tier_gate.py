"""The browser tier is collected only when ``-m`` selects it (archiver#546).

A command-line ``-m`` *replaces* a marker expression in ``addopts`` rather than
intersecting with it, so ``-m 'not browser'`` in ``addopts`` would not survive CI's
``pytest -m "not integration"`` (power-map ran its browser tier by accident that
way, #304). The tier is kept out at collection instead: ``tests/browser/`` imports
Playwright at module scope, and a run that did not ask for it never imports it.
A run that asks for it without the ``browser`` group fails at the conftest's
import, loudly, rather than skipping to green. Naming a path under
``tests/browser/`` is asking too (CR 3): pytest never consults the hook for an
explicit file, so the directory follows suit rather than collecting nothing.
"""

from pathlib import Path

import pytest

from tests.conftest import BROWSER_DIR, in_browser_tier, names_browser_path, selects_browser


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
    if names_browser_path(request.config.args, request.config.invocation_params.dir):
        pytest.skip("this run named a path in the browser tier")
    collected = [item for item in request.session.items if in_browser_tier(item.path)]
    assert collected == []


def test_a_path_through_a_symlink_is_still_the_tier(tmp_path: Path) -> None:
    """CR 2: the checkout reached through a link must not slip the gate."""
    link = tmp_path / "checkout"
    link.symlink_to(BROWSER_DIR.parent.parent)
    assert in_browser_tier(link / "tests" / "browser")
    assert in_browser_tier(link / "tests" / "browser" / "test_server.py")
    assert not in_browser_tier(link / "tests")
    assert not in_browser_tier(link / "tests" / "dashboard" / "test_home.py")


def test_naming_a_path_in_the_tier_asks_for_it() -> None:
    root = BROWSER_DIR.parent.parent
    assert names_browser_path(["tests/browser"], root)
    assert names_browser_path(["tests/browser/test_server.py::test_x"], root)
    assert names_browser_path(["browser/test_server.py"], root / "tests")


def test_the_default_paths_do_not() -> None:
    root = BROWSER_DIR.parent.parent
    assert not names_browser_path([], root)
    assert not names_browser_path(["tests"], root)
    assert not names_browser_path(["tests/dashboard", "tests/conftest.py"], root)
