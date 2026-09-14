"""``.skills/doc-sections`` must route doc-check hits at docs that exist.

archiver#228 (upstream gregoryfoster/skills#261, #284): on a hit, ``doc-check.sh``
prints the changed paths that matched ``.skills/doc-sensitive-paths`` and then the
doc sections to spot-check. Archiver tailored the list in #190 but not the advice,
so every hit named the python-fastapi defaults - AGENTS.md's "route table" and a
README quick start - whatever had changed. Upstream #284 now ends such a hit with
a note naming the untailored half; committing ``.skills/doc-sections`` is the fix.

Upstream deliberately runs no dead-entry check on advice, since it is prose. That
leaves the rot ``test_doc_sensitive_paths`` closes for the list: a renamed doc
keeps printing under its old name. This module checks the parts of the prose that
are checkable - every path it names is tracked, every ``doc "Heading"`` pair
resolves to a heading in that doc, and every line names a doc. Whether a line
routes a given list entry stays unchecked, for upstream's reason: a checker for
it is satisfied by pasting paths into the advice, which makes the advice worse.
"""

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SECTIONS = REPO_ROOT / ".skills" / "doc-sections"
SHIPPING_SKILL = REPO_ROOT / "skills" / "shipping-work-python-fastapi" / "SKILL.md"

# A repo-relative file path, in one of three shapes: under a directory with any
# extension (`deploy/archiver.service`); under a dot-directory with or without one
# (`.skills/doc-sections`); or a bare root name, by known extension only. The last
# is narrow because a bare `\w.\w` is also prose (`e.g.`), and extensionless paths
# need the leading dot because `owner/repo` slugs are prose too. The lookarounds
# keep a match from starting mid-path or stopping short of a longer one
# (`pyproject.toml.bak`).
FILE_TOKEN = re.compile(
    r"(?<![\w/.-])("
    r"(?:[\w.-]+/)+[\w-]+(?:\.\w+)+"
    r"|\.[\w-]+(?:/[\w.-]*\w)+"
    r"|[\w-]+\.(?:md|py|sh|toml|lock|json)"
    r")(?![\w/-]|\.\w)"
)
# A directory path, written the way the path list writes one: trailing slash.
DIR_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+)(?![\w.-])")
# `docs/X.md "Heading"` - a doc followed by the heading the reader should open.
HEADING_REF = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.md) "([^"]+)"')
# A code fence's opening or closing marker; a fence closes on the marker it opened with.
FENCE = re.compile(r"\s*(```|~~~)")


@cache
def _sections() -> tuple[str, ...]:
    """Parsed ``.skills/doc-sections``, read the way ``doc-check.sh`` reads it.

    Blank lines and lines whose first non-space character is ``#`` are dropped;
    a ``#`` later in a line is content. Tolerates the file being absent so a
    missing file fails one readable assertion instead of breaking collection.
    """
    if not SECTIONS.is_file():
        return ()
    lines = SECTIONS.read_text().splitlines()
    return tuple(
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    )


@cache
def _tracked_files() -> tuple[str, ...]:
    """Every tracked path, as ``doc-check.sh`` sees them."""
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(result.stdout.splitlines())


def _tokens(pattern: re.Pattern[str]) -> list[str]:
    """Every distinct match of ``pattern`` across the parsed sections, in order."""
    found = (match for section in _sections() for match in pattern.findall(section))
    return list(dict.fromkeys(found))


def _heading_refs() -> list[tuple[str, str]]:
    """Every distinct ``doc "Heading"`` pair across the parsed sections."""
    found = (ref for section in _sections() for ref in HEADING_REF.findall(section))
    return list(dict.fromkeys(found))


def _headings(text: str) -> list[str]:
    """ATX heading lines of ``text``, skipping fenced code, where ``#`` opens a comment."""
    headings: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        if marker := FENCE.match(line):
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1) == fence:
                fence = None
            continue
        if fence is None and re.match(r"#+\s", line):
            headings.append(line)
    return headings


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("deploy/archiver.service units", ["deploy/archiver.service"]),
        ("src/dashboard/static/dashboard.css", ["src/dashboard/static/dashboard.css"]),
        ("see .github/workflows/ci.yml.", [".github/workflows/ci.yml"]),
        ("`.skills/doc-sensitive-paths`", [".skills/doc-sensitive-paths"]),
        ("CHANGELOG.md: an entry", ["CHANGELOG.md"]),
        ("e.g. CannObserv/broker or gregoryfoster/skills#284", []),
        ("pyproject.toml.bak", []),
    ],
)
def test_file_token_grammar(text: str, expected: list[str]) -> None:
    """Pin what counts as a named path, so the checks below cannot quietly narrow."""
    assert FILE_TOKEN.findall(text) == expected


def test_headings_skip_fenced_code() -> None:
    """A ``#`` comment inside a code block is not a heading a reader can open."""
    text = "## Run locally\n```bash\n# Plain lookup\n~~~\n```\n### After\n~~~\n# Nope\n~~~\n"
    assert _headings(text) == ["## Run locally", "### After"]


def test_sections_file_is_committed_and_non_empty() -> None:
    """An absent file prints the skill's defaults and, since #284, a note about it."""
    assert SECTIONS.is_file(), f"{SECTIONS} is missing"
    assert _sections(), f"{SECTIONS} lists no sections"


def test_no_duplicate_sections() -> None:
    """A duplicate is a merge artifact; it prints twice on every hit."""
    sections = _sections()
    duplicates = {section for section in sections if sections.count(section) > 1}
    assert not duplicates, f"duplicate lines in {SECTIONS.name}: {sorted(duplicates)}"


@pytest.mark.parametrize("section", _sections())
def test_section_names_a_doc(section: str) -> None:
    """Advice that names no doc sends the reader nowhere - the defaults' failure."""
    assert any(token.endswith(".md") for token in FILE_TOKEN.findall(section)), (
        f"{section!r} names no .md doc; each line should say which doc a hit sends the reader to."
    )


@pytest.mark.parametrize("path", _tokens(FILE_TOKEN))
def test_named_file_is_tracked(path: str) -> None:
    """A renamed doc would keep printing under its old name; upstream never checks."""
    assert path in _tracked_files(), (
        f"{SECTIONS.name} names {path!r}, which is not a tracked file. Name it by "
        f"its repo-relative path, or follow the rename."
    )


@pytest.mark.parametrize("path", _tokens(DIR_TOKEN))
def test_named_directory_holds_tracked_files(path: str) -> None:
    """A directory the advice routes must still be a directory in this tree."""
    assert any(file.startswith(path) for file in _tracked_files()), (
        f"{SECTIONS.name} names {path!r}, which holds no tracked file."
    )


@pytest.mark.parametrize(("doc", "heading"), _heading_refs())
def test_quoted_heading_exists(doc: str, heading: str) -> None:
    """A quoted heading is the anchor a reader searches for; it must still be one."""
    headings = _headings((REPO_ROOT / doc).read_text())
    assert any(heading in line for line in headings), (
        f"{SECTIONS.name} sends the reader to {doc} {heading!r}, but no heading there contains it."
    )


@pytest.mark.parametrize("override", [".skills/doc-sensitive-paths", ".skills/doc-sections"])
def test_shipping_skill_introduces_each_override(override: str) -> None:
    """The forked Step 1.5 must name each file ``doc-check.sh`` reports on.

    ``skills/shipping-work-python-fastapi/SKILL.md`` is a committed fork, not a
    symlink, so upstream's own Step 1.5 never reaches it. #284's note names
    ``.skills/doc-sections``; an agent following a fork that never mentions it
    meets a file its instructions never introduced.
    """
    assert override in SHIPPING_SKILL.read_text(), (
        f"{SHIPPING_SKILL.relative_to(REPO_ROOT)} never mentions {override}; "
        f"re-sync Step 1.5 from the vendored skill."
    )
