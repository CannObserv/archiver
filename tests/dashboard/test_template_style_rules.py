"""Structural tripwires for the styling rules docs/STYLE.md states in prose.

A rule that lives only in a doc is one an unrelated commit can undo without
anything noticing — which is exactly how the inline margin this guard forbids
reached `domains/detail.html` in the first place (archiver#176).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "dashboard" / "templates"

# Components whose own class owns their outer spacing. An inline margin on one
# of these is either a no-op that collapses against the neighbour's margin, or a
# sign the neighbour is missing one and the fix belongs in the stylesheet.
_SPACING_OWNING_CLASSES = ("section-heading", "pagination")


def _tag_pattern(css_class: str) -> re.Pattern[str]:
    """Opening tag carrying ``css_class``, non-greedy to the first `>`.

    Non-greedy so one match is one tag rather than a run of them, and the class
    is matched inside the attribute value so `pagination` does not also catch a
    hypothetical `pagination__btn`.
    """
    return re.compile(rf"<[a-zA-Z][^>]*\bclass=\"[^\"]*\b{css_class}\b[^\"]*\"[^>]*>")


_SECTION_HEADING_TAG = _tag_pattern("section-heading")


def _template_files() -> list[Path]:
    return sorted(_TEMPLATES.rglob("*.html"))


def test_templates_exist() -> None:
    """Non-vacuity: a guard that walks nothing passes forever."""
    files = _template_files()
    assert len(files) > 20, f"expected the dashboard template tree, found {len(files)}"
    for css_class in _SPACING_OWNING_CLASSES:
        pattern = _tag_pattern(css_class)
        assert any(pattern.search(f.read_text()) for f in files), (
            f"no .{css_class} found — the guard below would be vacuous"
        )


@pytest.mark.parametrize("css_class", _SPACING_OWNING_CLASSES)
def test_no_inline_margin_on_spacing_owning_class(css_class: str) -> None:
    """These classes own their spacing; templates must not override it inline.

    Spacing above a `.section-heading` or a `.pagination` comes from the
    preceding element's bottom margin — `.entity-card` and `.data-table` both
    carry one — or from the class itself. An inline `margin-top` is therefore
    either a no-op that collapses against the neighbour's margin, or a sign the
    neighbour is missing one and the fix belongs in the stylesheet. Both cases
    are real: the `.section-heading` override removed in archiver#176 was the
    former, and the `.data-table` rule added in the same issue was the latter.
    See docs/STYLE.md § Data display.
    """
    pattern = _tag_pattern(css_class)
    offenders = []
    for path in _template_files():
        for tag in pattern.findall(path.read_text()):
            if re.search(r"style=\"[^\"]*margin", tag):
                offenders.append(f"{path.relative_to(_TEMPLATES)} :: {tag}")

    assert not offenders, f"inline margin on .{css_class}:\n  " + "\n  ".join(offenders)


# ---------------------------------------------------------------------------
# The Watcher panel's layout contract (archiver#181)
#
# Two things about this panel are load-bearing and invisible in the markup, so
# an unrelated commit can undo either without a template diff showing it.
# ---------------------------------------------------------------------------

_CSS = Path(__file__).resolve().parents[2] / "src" / "dashboard" / "static" / "dashboard.css"


def _rule(selector: str, css: str) -> str:
    """The declaration block for ``selector``, or "" when it has no rule.

    Anchored at a line start so `.detail-row` does not also match
    `.watch-panel__header + .detail-row`.
    """
    match = re.search(
        rf"^{re.escape(selector)}\s*\{{(.*?)\}}",
        css,
        re.M | re.S,
    )
    return match.group(1) if match else ""


def test_the_pause_toggle_is_anchored_without_taking_a_row() -> None:
    """The header is pulled out of flow, so row one starts at the panel's top.

    It was a block-level flex row of its own, which cost a full button's height
    of vertical space for one control. Out of flow it needs a gutter beside it
    instead, or the first row's cells run underneath the button.
    """
    css = _CSS.read_text()

    assert "position: relative" in _rule(".watch-panel", css), (
        ".watch-panel must establish a containing block for its header"
    )
    assert "position: absolute" in _rule(".watch-panel__header", css), (
        "the header must be out of flow, or it takes a row of its own again"
    )
    gutter = _rule(".watch-panel__header + .detail-row", css)
    assert "padding-right" in gutter, (
        "the row after the header must reserve space for the button it sits beside"
    )
    # Once the row is 1-up the gutter narrows to the one cell actually beside
    # the button, instead of indenting the cells stacked below it.
    assert ".watch-panel__header + .detail-row > .detail-grid__item:first-child" in css


def test_the_detail_row_steps_three_two_one_across_breakpoints() -> None:
    """An explicit column progression, not a flex squeeze.

    `flex: 1 1 12rem` let the three cells shrink instead of wrapping, so a
    narrow viewport got three cramped columns rather than one readable one.
    """
    css = _CSS.read_text()

    base = _rule(".detail-row", css)
    assert "grid-template-columns" in base, ".detail-row must declare its columns"
    assert "repeat(3," in base, "three columns at full width"

    # Both narrower steps live in media queries, so pull every override.
    overrides = re.findall(r"\.detail-row\s*\{([^}]*grid-template-columns[^}]*)\}", css)
    assert any("repeat(2," in o for o in overrides), "no 2-column step"
    assert any(
        "repeat(2," not in o and "repeat(3," not in o and "grid-template-columns" in o
        for o in overrides
    ), "no single-column step"

    # minmax(0, …) is what lets a track shrink below its content's min-width;
    # without it the cells refuse to narrow and the row overflows the viewport,
    # which is the defect this replaced.
    assert "minmax(0," in base
