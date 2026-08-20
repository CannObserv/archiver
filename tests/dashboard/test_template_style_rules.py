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
