"""Structural tripwires for the styling rules docs/STYLE.md states in prose.

A rule that lives only in a doc is one an unrelated commit can undo without
anything noticing — which is exactly how the inline margin this guard forbids
reached `domains/detail.html` in the first place (archiver#176).
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "dashboard" / "templates"

# The opening tag of any element carrying class="section-heading". Non-greedy to
# the first `>`, so one match is one tag rather than a run of them.
_SECTION_HEADING_TAG = re.compile(r"<[a-zA-Z][^>]*\bclass=\"section-heading\"[^>]*>")


def _template_files() -> list[Path]:
    return sorted(_TEMPLATES.rglob("*.html"))


def test_templates_exist() -> None:
    """Non-vacuity: a guard that walks nothing passes forever."""
    files = _template_files()
    assert len(files) > 20, f"expected the dashboard template tree, found {len(files)}"
    assert any(_SECTION_HEADING_TAG.search(f.read_text()) for f in files), (
        "no .section-heading found — the guard below would be vacuous"
    )


def test_no_inline_margin_on_section_heading() -> None:
    """`.section-heading` owns its spacing; templates must not override it inline.

    Spacing above a section heading comes from the preceding element's own
    bottom margin — `.entity-card` and `.data-table` both carry one. An inline
    `margin-top` here is either a no-op that collapses against that margin, or a
    sign the preceding element is missing one and the fix belongs in the
    stylesheet. See docs/STYLE.md § Data display.
    """
    offenders = []
    for path in _template_files():
        for tag in _SECTION_HEADING_TAG.findall(path.read_text()):
            if re.search(r"style=\"[^\"]*margin", tag):
                offenders.append(f"{path.relative_to(_TEMPLATES)} :: {tag}")

    assert not offenders, "inline margin on .section-heading:\n  " + "\n  ".join(offenders)
