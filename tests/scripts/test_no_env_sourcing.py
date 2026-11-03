"""No tracked file sources an env file, bar one named exception (#452).

Sourcing runs the file as shell code, and ``set -a`` exports every name in it to
every child, PATs included. Agents copy what the repo shows them, so the rule is
textual: the string may appear only where it is history (``docs/plans/``,
``CHANGELOG.md``) or upstream's (``skills-vendor/``), and once in
``scripts/deploy.sh``'s ``env_value``. That one reads root's
``/etc/archiver/.env``, which nobody here can read to check that parsing it
matches sourcing; its subshell exports nothing outward and prints one name
(#452 D4, docs/DEPLOYMENT.md § Parse env files, never source them).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "set -a"
EXCLUDED = (":!docs/plans/", ":!CHANGELOG.md", ":!skills-vendor/")
EXCEPTION = "scripts/deploy.sh"


def _hits() -> list[str]:
    """``path:line`` for every tracked occurrence outside the excluded paths."""
    this = Path(__file__).relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "grep", "-n", "-F", NEEDLE, "--", ".", *EXCLUDED, f":!{this}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr  # 1: no match
    return [
        line.split(":", 2)[0] + ":" + line.split(":", 2)[1] for line in result.stdout.splitlines()
    ]


def test_only_deploy_sh_env_value_sources_an_env_file() -> None:
    hits = _hits()
    assert [hit for hit in hits if not hit.startswith(f"{EXCEPTION}:")] == []
    assert len(hits) == 1, hits


def test_the_exception_is_inside_env_value() -> None:
    """Named, so a second use in deploy.sh fails rather than riding the first's pass."""
    (hit,) = [hit for hit in _hits() if hit.startswith(f"{EXCEPTION}:")]
    line = int(hit.split(":")[1])
    lines = (REPO_ROOT / EXCEPTION).read_text().splitlines()
    start = next(i for i, text in enumerate(lines) if text.startswith("env_value()"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    assert start < line - 1 < end


@pytest.mark.parametrize("path", ["src/core/database.py", "alembic/env.py", "tests/conftest.py"])
def test_the_missing_url_hints_point_at_agents_md(path: str) -> None:
    """The hint is what an agent copies, so it names a section, not a recipe (D5)."""
    text = (REPO_ROOT / path).read_text()
    assert "Load env:" not in text
    assert "AGENTS.md § Environment Files" in text


def test_the_conftest_hint_names_the_gate() -> None:
    """``scripts/pre-ship.sh`` loads ``TEST_DATABASE_URL`` and nothing else."""
    assert "bash scripts/pre-ship.sh" in (REPO_ROOT / "tests" / "conftest.py").read_text()
