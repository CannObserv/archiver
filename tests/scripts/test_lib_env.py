"""``scripts/lib/env.sh``: archiver's allowlist over upstream's ``load_env`` (#452).

Sourcing an env file runs it as shell code and exports every name in it. The
repo ``.env`` holds PATs and API tokens, so archiver's two scripts that read it,
``scripts/pre-ship.sh`` and ``scripts/dev_server.sh``, parse it instead and
export only the names they need.

The parser is not copied here: the library lifts ``load_env`` from the recipe in
the vendored gate's header, the one copy (gregoryfoster/skills#517), and adds
``load_env_only`` on top. The tests run the library in a bash child and read what
it exported from a probe file, so no value reaches the test's output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "lib" / "env.sh"
RECIPE = Path("skills/shipping-work/scripts/pre-ship.sh")

SECRET = "ghp_not-a-real-token"
DEV_URL = "postgresql:///archiver_dev"
TEST_URL = "postgresql://u:p w@localhost/archiver_test"
ENV_TEXT = f"""\
# dev/agent secrets
TEST_DATABASE_URL="{TEST_URL}"
GH_TOKEN={SECRET}
  export ANTHROPIC_API_KEY='{SECRET}-2'
ARCHIVER_DEV_DATABASE_URL={DEV_URL}
ARCHIVER_DEVX=not-a-dev-knob
not a pair
"""
DEV_SERVER_NAMES = "ARCHIVER_DEV_* TEST_DATABASE_URL"


def _run(tree: Path, script: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """Source the library from ``tree`` in a bash child, then run ``script``."""
    probe = tmp_path / "probe"
    probe.mkdir(exist_ok=True)
    base = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PROBE": str(probe)}
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail; . "{tree}/scripts/lib/env.sh"; {script}'],
        cwd=tmp_path,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seen(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / "probe" / "env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.env"
    path.write_text(ENV_TEXT)
    return path


def test_exports_only_the_names_that_match(env_file: Path, tmp_path: Path) -> None:
    result = _run(
        REPO_ROOT,
        f'load_env_only "{DEV_SERVER_NAMES}" "{env_file}"; env > "$PROBE/env"',
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    seen = _seen(tmp_path)
    assert seen["ARCHIVER_DEV_DATABASE_URL"] == DEV_URL
    assert seen["TEST_DATABASE_URL"] == TEST_URL, "quotes stripped, spaces kept"
    for name in ("GH_TOKEN", "ANTHROPIC_API_KEY", "ARCHIVER_DEVX"):
        assert name not in seen, name


def test_an_exact_name_is_not_a_prefix(env_file: Path, tmp_path: Path) -> None:
    result = _run(
        REPO_ROOT,
        f'load_env_only "ARCHIVER_DEV" "{env_file}"; env > "$PROBE/env"',
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert not [name for name in _seen(tmp_path) if name.startswith("ARCHIVER_DEV")]


def test_env_names_lists_what_the_file_set(env_file: Path, tmp_path: Path) -> None:
    """Names only, for pre-ship's stamp key. An inherited value the file does not
    set is not the file's, so it is not listed, and it is left as it was."""
    result = _run(
        REPO_ROOT,
        f'load_env_only "{DEV_SERVER_NAMES} ARCHIVER_DEV_PORT" "{env_file}"; '
        'echo "$ENV_NAMES" > "$PROBE/names"; env > "$PROBE/env"',
        tmp_path,
        ARCHIVER_DEV_PORT="8002",
    )
    assert result.returncode == 0, result.stderr
    names = (tmp_path / "probe" / "names").read_text().split()
    assert sorted(names) == ["ARCHIVER_DEV_DATABASE_URL", "TEST_DATABASE_URL"]
    assert _seen(tmp_path)["ARCHIVER_DEV_PORT"] == "8002"


def test_the_file_wins_over_an_inherited_value(env_file: Path, tmp_path: Path) -> None:
    """As in upstream's recipe, and as sourcing did."""
    _run(
        REPO_ROOT,
        f'load_env_only "TEST_DATABASE_URL" "{env_file}"; env > "$PROBE/env"',
        tmp_path,
        TEST_DATABASE_URL="postgresql:///archiver",
    )
    assert _seen(tmp_path)["TEST_DATABASE_URL"] == TEST_URL


def test_an_unmatched_inherited_name_passes_through(env_file: Path, tmp_path: Path) -> None:
    """The filter governs what the file exports, not the caller's environment."""
    _run(
        REPO_ROOT,
        f'load_env_only "TEST_DATABASE_URL" "{env_file}"; env > "$PROBE/env"',
        tmp_path,
        GH_TOKEN="inherited",
    )
    assert _seen(tmp_path)["GH_TOKEN"] == "inherited"


def test_a_pattern_never_globs_against_the_directory(env_file: Path, tmp_path: Path) -> None:
    """An unquoted ``ARCHIVER_DEV_*`` would expand to a file of that name."""
    (tmp_path / "ARCHIVER_DEV_DATABASE_URL.bak").write_text("")
    _run(
        REPO_ROOT,
        f'load_env_only "ARCHIVER_DEV_*" "{env_file}"; env > "$PROBE/env"',
        tmp_path,
    )
    assert _seen(tmp_path)["ARCHIVER_DEV_DATABASE_URL"] == DEV_URL


def test_never_prints_a_value(env_file: Path, tmp_path: Path) -> None:
    result = _run(REPO_ROOT, f'load_env_only "{DEV_SERVER_NAMES}" "{env_file}"', tmp_path)
    assert result.returncode == 0, result.stderr
    for value in (TEST_URL, DEV_URL, SECRET):
        assert value not in result.stdout + result.stderr


def test_a_missing_file_loads_nothing(tmp_path: Path) -> None:
    result = _run(
        REPO_ROOT,
        f'load_env_only "TEST_DATABASE_URL" "{tmp_path}/absent"; '
        'echo "[$ENV_NAMES]" > "$PROBE/names"',
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "probe" / "names").read_text() == "[]\n"


def test_load_env_is_upstreams_not_a_copy() -> None:
    """The library lifts the parser from the recipe; it carries no parser itself."""
    text = LIB.read_text()
    assert str(RECIPE) in text
    assert "while IFS= read -r line" not in text


def test_a_missing_recipe_names_the_fix(tmp_path: Path) -> None:
    """An unpopulated submodule leaves no recipe to lift: exit 2, as the gate does."""
    tree = tmp_path / "tree"
    (tree / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(LIB, tree / "scripts" / "lib" / "env.sh")
    result = _run(tree, "true", tmp_path)
    assert result.returncode == 2
    assert "git submodule update --init --recursive" in result.stderr


def test_a_recipe_without_load_env_names_the_fix(tmp_path: Path) -> None:
    """Upstream moving the recipe must fail here, not later as a missing URL."""
    tree = tmp_path / "tree"
    (tree / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(LIB, tree / "scripts" / "lib" / "env.sh")
    (tree / RECIPE).parent.mkdir(parents=True)
    (tree / RECIPE).write_text("#!/usr/bin/env bash\n# no recipe in this header\n")
    result = _run(tree, "true", tmp_path)
    assert result.returncode == 2
    assert "no load_env recipe" in result.stderr
    assert "git submodule update --init --recursive" in result.stderr


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_env_file_falls_back_to_the_primary_checkout(tmp_path: Path) -> None:
    """``.env`` is gitignored, so a linked worktree has none (upstream #497)."""
    primary = tmp_path / "repo"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    _git(
        primary,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "i",
    )
    tree = tmp_path / "wt"
    _git(primary, "worktree", "add", "-q", "-b", "feature", str(tree))

    result = _run(REPO_ROOT, f'env_file "{tree}"; env_file "{primary}"', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"{primary}/.env"] * 2

    (tree / ".env").write_text("")
    result = _run(REPO_ROOT, f'env_file "{tree}"', tmp_path)
    assert result.stdout.strip() == f"{tree}/.env"
