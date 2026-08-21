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


def _media_blocks(css: str) -> list[str]:
    r"""Every ``@media`` block's body, brace-matched.

    A regex cannot do this: `@media[^{]*\{` stops at the first brace, so it only
    ever sees the block's *first* rule. The likeliest way a viewport breakpoint
    comes back is somebody adding a selector to an existing block, which is
    exactly the case that pattern misses (CR round 3, finding 14).
    """
    blocks = []
    for start in (m.end() for m in re.finditer(r"@media[^{]*\{", css)):
        depth, i = 1, start
        while i < len(css) and depth:
            depth += (css[i] == "{") - (css[i] == "}")
            i += 1
        blocks.append(css[start : i - 1])
    return blocks


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
    # Every row after the header, not just the first (CR round 3, finding 12).
    # `auto-fit` counts columns from the container it is given, so a gutter on
    # one row alone makes that row compute a different column count from its
    # sibling - the two authored rows then misalign across ~96px-wide bands of
    # panel width, which is the alignment the pattern exists to guarantee.
    gutter = _rule(".watch-panel__header ~ .detail-row", css)
    assert "padding-right" in gutter, (
        "every row beside the button must reserve the same space, or the rows "
        "disagree about their column count"
    )
    assert not _rule(".watch-panel__header + .detail-row", css), (
        "an adjacent-sibling gutter reaches only the first row"
    )


def test_the_detail_row_wraps_on_its_container_not_the_viewport() -> None:
    """3 -> 2 -> 1 columns driven by the space the row actually has.

    The first attempt used viewport media queries, which cannot see the fixed
    sidebar: at a 1000px viewport the content column is ~555px, so a row keyed
    to `min-width: 900px` still laid out three columns and overflowed. `auto-fit`
    reads the container instead, so the sidebar is accounted for by construction.
    """
    css = _CSS.read_text()
    base = _rule(".detail-row", css)

    assert "grid-template-columns" in base
    assert "auto-fit" in base, "column count must follow the container, not the viewport"
    # `min(100%, …)` keeps the track from exceeding a container narrower than the
    # floor itself, which is what turns the last step into a clean single column
    # instead of an overflow.
    assert "min(100%," in base
    # The floor is a custom property so a screen with longer or terser values can
    # retune it without editing the shared rule (CR round 3, finding 16).
    assert "var(--detail-row-min" in base

    offenders = [b for b in _media_blocks(css) if re.search(r"(^|[,{}\s])\.detail-row\b", b)]
    assert not offenders, (
        "a viewport media query on .detail-row reintroduces the sidebar blind spot"
    )


def test_the_content_column_can_shrink_below_its_contents() -> None:
    """The defect behind the clipped topbar and the page-wide scrollbar.

    `.main-content` is a flex item, and a flex item defaults to
    `min-width: auto` - it will not shrink below its content's min-content
    width. A `.data-table` has a large one, so the table's width became the
    page's width: the fixed topbar (sized to the viewport) then ended
    mid-content and the whole document scrolled sideways.
    """
    css = _CSS.read_text()
    main = _rule(".main-content", css)

    assert "min-width: 0" in main, "a flex item that cannot shrink widens the page"
    assert "overflow-x" in main, "something still has to contain a table wider than the column"
