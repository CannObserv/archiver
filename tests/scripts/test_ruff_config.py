"""The ruff configuration's three deliberate choices, pinned against a version bump.

ruff 0.16 (archiver#242) did not change how a ``.py`` file is formatted here. It
changed three things around the edges, and each one is a decision this repo made
rather than a default it can inherit again:

1. **Markdown is in scope, with two exclusions.** 0.16's default ``include``
   adds ``*.md``, so ``ruff format`` now formats the ``python`` fences inside
   documentation. Kept, except for ``docs/plans/`` - dated snapshots of what was
   proposed, not maintained source - and ``skills/``, below.
2. **A vendored symlink must not be in ruff's path.** ``skills/`` overrides carry
   file-level symlinks into the ``skills-vendor/`` submodules, which the main CI
   workflow's ``actions/checkout`` does not check out. 0.16 reading a ``*.md``
   link that dangles there is an ``io: No such file or directory`` and a red
   build - no formatting opinion involved.
3. **The SDK selects its own rules.** ``clients/python/pyproject.toml`` carries a
   ``[tool.ruff]`` table, which makes it - not the root config - the one that
   governs every file beneath it. With no ``select`` it inherited ruff's
   *default* rule set, so 0.16 widening those defaults surfaced 91 findings in
   code nobody had touched. An explicit selection is what keeps a ruff release
   from redefining what the SDK is checked against.

The pins these rest on live in two files that have to move together: the
``ruff`` specifier in ``pyproject.toml`` and ``rev:`` in
``.pre-commit-config.yaml``. A skew there means the editor-time hook and CI
disagree about what is an error, which is the worst way to learn about a bump.
"""

import re
import tomllib
from functools import cache

import pytest

from tests.scripts._skills_lists import REPO_ROOT, tracked_files

ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
SDK_PYPROJECT = REPO_ROOT / "clients" / "python" / "pyproject.toml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

# Extensions ruff reads under its 0.16 defaults. ``.md`` is the new one, and the
# only one that reaches a vendored symlink here.
RUFF_EXTENSIONS = {".py", ".pyi", ".ipynb", ".md"}


@cache
def _root_ruff() -> dict:
    return tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]


@cache
def _sdk_ruff() -> dict:
    return tomllib.loads(SDK_PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]


@cache
def _submodule_paths() -> tuple[str, ...]:
    """Every ``path =`` in ``.gitmodules`` - the trees CI leaves empty."""
    text = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
    return tuple(m.group(1).strip() for m in re.finditer(r"^\s*path\s*=\s*(.+)$", text, re.M))


def _excluded(path: str) -> bool:
    """Whether the root config's ``exclude`` covers ``path`` (repo-relative)."""
    return any(path == pattern or path.startswith(pattern) for pattern in _root_ruff()["exclude"])


# --- the Markdown decision (#242) ----------------------------------------------


def test_markdown_stays_in_ruff_format_scope() -> None:
    """No blanket ``*.md`` opt-out: the live docs' code fences are formatted."""
    assert not any("*.md" in pattern for pattern in _root_ruff()["exclude"]), (
        "Markdown is in scope by decision; exclude specific trees, not the extension"
    )


def test_dated_plan_snapshots_are_excluded() -> None:
    """``docs/plans/`` records what was proposed; reformatting rewrites the record."""
    assert _excluded("docs/plans/2026-05-03-information-service-phase1-plan.md")


# --- the dangling-symlink guard (#242) -----------------------------------------


def _vendored_symlinks() -> list[str]:
    """Tracked symlinks in a ruff-read format whose target lives in a submodule.

    These are exactly the paths that resolve on a developer's checkout and dangle
    under the main CI workflow, which checks out no submodules.
    """
    found = []
    for path in tracked_files():
        candidate = REPO_ROOT / path
        if not candidate.is_symlink() or candidate.suffix not in RUFF_EXTENSIONS:
            continue
        target = (candidate.parent / candidate.readlink()).resolve()
        try:
            relative = target.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue
        if any(relative.startswith(f"{sub}/") for sub in _submodule_paths()):
            found.append(path)
    return found


def test_the_guard_has_something_to_guard() -> None:
    """A vendored symlink in ruff's formats still exists; otherwise this gate is inert."""
    assert _vendored_symlinks(), "no vendored symlink found - has the layout changed?"


@pytest.mark.parametrize("path", _vendored_symlinks())
def test_vendored_symlinks_are_outside_ruff_scope(path: str) -> None:
    """A link into an unchecked-out submodule is an io error, not a lint finding."""
    assert _excluded(path), (
        f"{path} links into a submodule CI does not check out; "
        "ruff would fail to read it. Exclude it from [tool.ruff]."
    )


# --- the SDK's own rule selection (#242) ---------------------------------------


def test_sdk_selects_its_rules_explicitly() -> None:
    """Its ``[tool.ruff]`` table governs the SDK; ruff's defaults must not."""
    assert _sdk_ruff().get("lint", {}).get("select"), (
        f"{SDK_PYPROJECT} owns every file beneath it. Without an explicit "
        "lint.select it tracks ruff's default rule set, which changes per release."
    )


def test_sdk_excludes_generated_from_lint_only() -> None:
    """``generated/`` is not hand-maintained - but ``regen.sh`` does format it."""
    sdk = _sdk_ruff()
    lint_exclude = sdk.get("lint", {}).get("exclude", [])
    assert any("generated" in pattern for pattern in lint_exclude), (
        "the root exclude never reaches the generated tree - the nested config "
        "is the one that governs it"
    )
    assert not any("generated" in pattern for pattern in sdk.get("exclude", [])), (
        "a top-level exclude here would also drop the tree from `ruff format`, "
        "which scripts/regen.sh and the client-drift gate both run over it"
    )


# --- the two pins that move together (#242) ------------------------------------


def _pinned_ruff_floor() -> str:
    """The lower bound of the root dev group's ``ruff`` specifier."""
    dev = tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))["dependency-groups"]["dev"]
    specifier = next(entry for entry in dev if entry.startswith("ruff"))
    return re.search(r">=\s*([0-9][^,]*)", specifier).group(1).strip()


def test_pre_commit_rev_matches_the_ruff_pin() -> None:
    """The hook and CI must agree on what counts as an error."""
    # Comment lines sit between the repo and its `rev:`, so match the first
    # `rev:` after the repo rather than the line right below it.
    rev = re.search(
        r"astral-sh/ruff-pre-commit\b.*?^\s*rev:\s*v?(\S+)",
        PRE_COMMIT.read_text(encoding="utf-8"),
        re.S | re.M,
    )
    assert rev, "could not find the ruff-pre-commit rev in .pre-commit-config.yaml"
    assert rev.group(1) == _pinned_ruff_floor()
