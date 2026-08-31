"""``.skills/doc-sensitive-paths`` must name paths that exist in this tree.

archiver#190 (upstream gregoryfoster/skills#252): ``doc-check.sh`` used to anchor
its entries at the start of the path, so ``pyproject.toml`` matched only the root
file and never ``clients/python/pyproject.toml``. The gate printed
``No sensitive paths changed`` and exited 0 - a miss byte-identical to a pass.
Upstream now matches whole path *segments*, treats a list where **no** entry
matches any tracked file as exit 2, and lets a project replace the defaults by
committing ``.skills/doc-sensitive-paths``.

That override is a plain text file with no schema and no CI of its own: a
renamed directory turns an entry into a dead one silently, and dead entries are
exactly what the upstream defaults had here (``schema.sql``, ``src/models/``,
``.env.example`` match nothing in this repo). Upstream's exit-2 guard only fires
when *every* entry is dead; a list that is half-dead still prints green. This
module closes that gap for archiver's tailored list: each entry must match a
tracked file, and the changelog-trigger paths must each be covered by some entry.

The matcher below mirrors ``path_matches`` in the vendored ``doc-check.sh``. It
is a deliberate second copy rather than a shell-out: the point is to assert what
the list means, and a test that re-ran the script under test would only prove the
script agrees with itself.
"""

import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PATH_LIST = REPO_ROOT / ".skills" / "doc-sensitive-paths"
CHANGELOG_LIB = REPO_ROOT / "scripts" / "check_changelog_lib.sh"

# Sample paths under the changelog trigger: the change class this project
# already calls contract-visible. A doc gate blind to any of them would miss it.
# Derived below from the gate's own regex, not from prose - AGENTS.md describes
# the rule, `check_changelog_lib.sh` is the rule.
CHANGELOG_TRIGGER_PATHS = (
    "alembic/versions/0001_initial.py",
    "src/api/routes/info_items.py",
    "src/api/schemas/info_item.py",
    "clients/python/pyproject.toml",
)

# Glob metacharacters. `doc-check.sh` matches entries with bash `case`, which
# expands them; _matches below compares literally. An entry carrying one would
# mean two different things to the gate and to this test.
GLOB_METACHARACTERS = ("*", "?", "[")


@cache
def _entries() -> tuple[str, ...]:
    """Parsed ``.skills/doc-sensitive-paths``: blank lines and ``#`` comments out.

    Tolerates the file being absent so a missing list fails one readable
    assertion instead of breaking collection for the whole module.
    """
    if not PATH_LIST.is_file():
        return ()
    lines = PATH_LIST.read_text().splitlines()
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


def _matches(file: str, entry: str) -> bool:
    """Segment match, mirroring ``path_matches`` in the vendored ``doc-check.sh``."""
    if entry.endswith("/"):
        return file.startswith(entry) or f"/{entry}" in file
    return (
        file == entry
        or file.endswith(f"/{entry}")
        or file.startswith(f"{entry}/")
        or f"/{entry}/" in file
    )


def test_path_list_is_committed_and_non_empty() -> None:
    """An absent or empty list silently reverts the gate to upstream defaults."""
    assert PATH_LIST.is_file(), f"{PATH_LIST} is missing"
    assert _entries(), f"{PATH_LIST} lists no paths"


def test_no_duplicate_entries() -> None:
    """A duplicate is a merge artifact, not a stronger match."""
    entries = _entries()
    duplicates = {entry for entry in entries if entries.count(entry) > 1}
    assert not duplicates, f"duplicate entries in {PATH_LIST.name}: {sorted(duplicates)}"


@pytest.mark.parametrize("entry", _entries())
def test_entry_matches_a_tracked_file(entry: str) -> None:
    """A dead entry is a gate that cannot fire - the #252 failure, list-side."""
    tracked = _tracked_files()
    assert any(_matches(file, entry) for file in tracked), (
        f"{entry!r} matches no tracked file. Either the path was renamed and the "
        f"entry should follow it, or the entry is dead and should be removed."
    )


@pytest.mark.parametrize("path", CHANGELOG_TRIGGER_PATHS)
def test_changelog_trigger_paths_are_covered(path: str) -> None:
    """Every contract-visible path the changelog guard watches is also doc-watched."""
    assert any(_matches(path, entry) for entry in _entries()), (
        f"{path} triggers the changelog guard but matches no entry in "
        f"{PATH_LIST.name}; a doc-sensitive change there would ship unflagged."
    )


def _changelog_trigger_re() -> str:
    """``CHANGELOG_TRIGGER_RE`` as the pre-push guard and CI actually define it."""
    match = re.search(r"^CHANGELOG_TRIGGER_RE='([^']+)'", CHANGELOG_LIB.read_text(), re.MULTILINE)
    assert match, f"CHANGELOG_TRIGGER_RE not found in {CHANGELOG_LIB.name}"
    return match.group(1)


def test_changelog_trigger_paths_match_the_gate_regex() -> None:
    """Pin the sample paths to the gate's regex, not to a doc that describes it."""
    trigger = re.compile(_changelog_trigger_re())
    for path in CHANGELOG_TRIGGER_PATHS:
        assert trigger.match(path), (
            f"{path} no longer matches {trigger.pattern}; the trigger moved and "
            f"CHANGELOG_TRIGGER_PATHS should follow it."
        )


def test_agents_md_quotes_the_gate_regex() -> None:
    """AGENTS.md documents the trigger verbatim; drift there misleads every agent."""
    assert _changelog_trigger_re() in (REPO_ROOT / "AGENTS.md").read_text(), (
        f"AGENTS.md does not quote {CHANGELOG_LIB.name}'s CHANGELOG_TRIGGER_RE "
        f"verbatim; the documented trigger has drifted from the enforced one."
    )


@pytest.mark.parametrize("entry", _entries())
def test_entry_carries_no_glob_metacharacters(entry: str) -> None:
    """Bash `case` would expand one; the matcher mirrored here would not."""
    found = [char for char in GLOB_METACHARACTERS if char in entry]
    assert not found, (
        f"{entry!r} contains {found}, which bash `case` expands as a glob but "
        f"this test compares literally. Write the path out instead."
    )
