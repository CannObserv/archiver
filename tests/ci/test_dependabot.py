"""Pin ``.github/dependabot.yml``, the bot that proposes action bumps (#192),
and the workflow pins it moves.

Dependabot's config fails silently: a mistyped ecosystem, a bad directory or a
missing schedule stops producing PRs without erroring anywhere a person looks,
and a quiet bot reads like "no updates available". Ported from
CannObserv/watcher's ``tests/ci/test_dependabot.py``, with broker's exclusion:

* **``github-actions`` only.** ``uv`` waits on #192's blocker 2: co-core
  resolves only from the private wheelhouse, which Dependabot's updater cannot
  sync. npm's ``"latest"`` specifiers and ``skills-vendor/``'s deliberate
  submodule bumps stay out too. Any second block fails here.
* **``context-cadence.yml`` is excluded.** ``install-cadence.sh`` generates it,
  and a re-render reverts any bump made in it (gregoryfoster/skills#373). Its
  pin moves with the installer, so the pin rule reads every *other* workflow.
* **The open-PR limit outlasts a full batch.** Past the limit (default 5)
  Dependabot opens nothing and says so nowhere (notifier#103). One PR per
  action, so the bound is derived from the workflows rather than transcribed.
* **Commits match CLAUDE.md's no-issue form**, ``<type>: <description>``.
* **Every scanned ``uses:`` pins a commit SHA with its version comment.**
  Dependabot proposes refs in the pin's own form, so a floating major goes
  silent once upstream stops tagging majors (setup-uv after v7), and a moved
  tag is the tj-actions attack. The comment is what Dependabot reads and
  rewrites alongside the SHA. That a SHA *is* its tag needs the network, so it
  is checked by hand when a pin moves:
  ``git ls-remote --tags https://github.com/<owner>/<action>``.

Pure file reads: no network, no database.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GENERATED = ".github/workflows/context-cadence.yml"

# CLAUDE.md → Conventions → Commit Messages.
COMMIT_TYPES = {"feat", "fix", "refactor", "docs", "test", "chore"}

# `owner/repo@ref` or `owner/repo/path@ref`: what the github-actions updater bumps.
_ACTION = re.compile(r"^([\w.-]+/[\w.-]+)(?:/[^@]*)?@.+$")

# A `uses:` line as written, comment included: the parsed YAML drops comments.
_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
# `<40-hex SHA> # vX.Y.Z`, the form Dependabot keeps in step.
_SHA_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+$")


def _load() -> dict:
    """The parsed config, or an empty document while the file is missing.

    Tolerating absence keeps collection alive, so the failure surfaces as
    ``test_config_exists``'s message rather than a collection error.
    """
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) if CONFIG.is_file() else {}


def _updates() -> list[dict]:
    return _load().get("updates", [])


def _directories(block: dict) -> set[str]:
    """A block's directories, whichever of the two spellings it uses."""
    return set(block.get("directories", [])) | (
        {block["directory"]} if "directory" in block else set()
    )


def _scanned() -> list[Path]:
    """The workflows Dependabot reads: all but the generated one."""
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        if path.relative_to(REPO_ROOT).as_posix() != GENERATED
    ]


def _uses(node: object) -> list[str]:
    """Every ``uses:`` value in a parsed workflow, at any depth."""
    if isinstance(node, dict):
        found = [node["uses"]] if isinstance(node.get("uses"), str) else []
        return found + [u for value in node.values() for u in _uses(value)]
    if isinstance(node, list):
        return [u for item in node for u in _uses(item)]
    return []


def _parsed_refs() -> list[str]:
    return [u for path in _scanned() for u in _uses(yaml.safe_load(path.read_text("utf-8")))]


def _actions() -> set[str]:
    """The distinct ``owner/repo`` actions the scanned workflows pin: one PR each."""
    return {m.group(1) for ref in _parsed_refs() if (m := _ACTION.match(ref))}


def _uses_lines() -> list[tuple[str, int, str, str]]:
    """Every scanned ``uses:`` line: (file, line, ref, rest of line)."""
    return [
        (path.name, n, m.group(1), m.group(2))
        for path in _scanned()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if (m := _USES_LINE.match(line))
    ]


def _is_pinned(ref: str, rest: str) -> bool:
    """A SHA pin with its version comment, or a ``./`` action in this repo."""
    return ref.startswith("./") or bool(_SHA_PIN.match(ref) and _VERSION_COMMENT.match(rest))


def test_config_exists() -> None:
    assert CONFIG.is_file(), (
        "no .github/dependabot.yml: nothing proposes the action bumps the "
        "workflows' pins make invisible (#192)"
    )


def test_config_is_version_2() -> None:
    """Version 1 configs are dead; Dependabot ignores them without erroring."""
    assert _load().get("version") == 2


def test_only_github_actions_is_configured() -> None:
    ecosystems = [u.get("package-ecosystem") for u in _updates()]
    assert ecosystems == ["github-actions"], (
        f"ecosystems {ecosystems}: #192 ships github-actions alone. A `uv` block "
        "needs the private wheelhouse reachable from Dependabot's updater; npm "
        "and gitsubmodule are their own decisions, not this file's"
    )


@pytest.fixture
def actions_block() -> dict:
    blocks = [u for u in _updates() if u.get("package-ecosystem") == "github-actions"]
    assert len(blocks) == 1, f"expected one github-actions block, found {len(blocks)}"
    return blocks[0]


def test_actions_block_covers_the_workflows(actions_block: dict) -> None:
    """``/`` is the spelling that scans ``.github/workflows/``; any other is silence."""
    assert _directories(actions_block) == {"/"}


def test_actions_block_excludes_only_the_generated_workflow(actions_block: dict) -> None:
    """A re-render of the cadence workflow reverts a bump (skills#373); nothing
    else is excluded, or its pins would go stale with nobody told."""
    assert actions_block.get("exclude-paths") == [GENERATED]
    assert (REPO_ROOT / GENERATED).is_file(), f"{GENERATED} moved: re-point the exclusion"


def test_actions_block_runs_weekly(actions_block: dict) -> None:
    """No interval is a config Dependabot rejects, visibly only in the repo's
    Dependabot tab, which nobody watches."""
    assert actions_block.get("schedule", {}).get("interval") == "weekly"


def test_open_pr_limit_outlasts_a_full_batch(actions_block: dict) -> None:
    actions = _actions()
    assert actions, "found no `uses:` in .github/workflows/: the derivation broke"
    limit = actions_block.get("open-pull-requests-limit", 5)
    assert limit > len(actions), (
        f"limit {limit} can be filled by {len(actions)} action PRs ({sorted(actions)}); "
        "past it Dependabot opens nothing and says so nowhere. Raise "
        "open-pull-requests-limit"
    )


def test_commits_follow_the_repo_convention(actions_block: dict) -> None:
    """The PR's commit reaches ``main`` through a merge commit, so it must read like ours."""
    prefix = actions_block.get("commit-message", {}).get("prefix")
    assert prefix in COMMIT_TYPES, (
        f"commit-message.prefix {prefix!r}: Dependabot's default 'Bump …' subject "
        f"matches none of CLAUDE.md's types {sorted(COMMIT_TYPES)}"
    )


def test_every_uses_line_is_read() -> None:
    """The line scan sees every ``uses:`` the parser does, so none escapes the pin rule."""
    assert sorted(ref for _, _, ref, _ in _uses_lines()) == sorted(_parsed_refs()), (
        "the line scan and the YAML parser disagree on the `uses:` refs: a quoted "
        "ref, a flow-style step or a `uses:` line inside a `run:` block. Write each "
        "step's `uses:` unquoted, on its own line, so the pin rule can read it"
    )


def test_every_action_is_sha_pinned_with_its_version() -> None:
    bad = [
        f"{name}:{n}: {ref}{rest}"
        for name, n, ref, rest in _uses_lines()
        if not _is_pinned(ref, rest)
    ]
    assert not bad, (
        "pin each action as `owner/action@<40-hex sha> # vX.Y.Z`: a tag moves, "
        "and a floating major goes stale once upstream stops publishing it. "
        "Offending lines:\n  " + "\n  ".join(bad)
    )


def test_pin_rule_rejects_a_tag_and_accepts_a_local_action() -> None:
    """``./`` actions live in this repo: no tag to move, nothing to pin."""
    assert _is_pinned("./.github/actions/setup", "")
    assert not _is_pinned("actions/checkout@v7", "")
    assert not _is_pinned("actions/checkout@" + "0" * 40, "")
    assert _is_pinned("actions/checkout@" + "0" * 40, " # v7.0.1")
