"""``scripts/pre-ship.sh`` loads the one variable the gate needs, then execs it (#457).

The unified ``shipping-work`` skill resolves each script on its own, so a repo-root
``scripts/pre-ship.sh`` replaces only the gate (gregoryfoster/skills#301). It follows
the recipe in the vendored gate's header - parse, never source; fall back to the
primary checkout's ``.env``; a missing delegate is exit 2; ``exec`` with ``"$@"`` -
with two departures (#457 D2):

- **No ``/etc/archiver/.env``.** It is root's alone (#339), so an agent shell skips
  it; under ``sudo`` it would hand the test run production's database URL.
- **An allowlist.** The repo ``.env`` holds ~20 names, and only
  ``TEST_DATABASE_URL`` is a test input; the rest are PATs and API tokens that no
  pytest subprocess needs (#452). The parser stays upstream's; only the export is
  filtered, and ``PRE_SHIP_ENV_NAMES`` lists what was exported for the stamp key.

The wrapper runs here in a scratch repo against a fake delegate that records the
environment and arguments it was handed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "pre-ship.sh"
DELEGATE = Path("skills/shipping-work/scripts/pre-ship.sh")

TEST_URL = "postgresql://u:p w@localhost/archiver_test"
SECRET = "ghp_not-a-real-token"
ENV_TEXT = f"""\
# dev/agent secrets
TEST_DATABASE_URL="{TEST_URL}"
GH_TOKEN={SECRET}
  export ANTHROPIC_API_KEY='{SECRET}-2'
ARCHIVER_DEV_DATABASE_URL=postgresql:///archiver_dev
not a pair
"""

# Records what the gate would see: every name with its value, then the argv.
FAKE_DELEGATE = """\
#!/usr/bin/env bash
env > "$PROBE/env"
printf '%s\\n' "$@" > "$PROBE/args"
exit "${FAKE_EXIT:-0}"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed scratch repo holding the wrapper and a fake delegate."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(WRAPPER, root / "scripts" / "pre-ship.sh")
    delegate = root / DELEGATE
    delegate.parent.mkdir(parents=True)
    delegate.write_text(FAKE_DELEGATE)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def _run(cwd: Path, tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    probe = tmp_path / "probe"
    probe.mkdir(exist_ok=True)
    base = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PROBE": str(probe)}
    return subprocess.run(
        ["bash", "scripts/pre-ship.sh", *args],
        cwd=cwd,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seen(tmp_path: Path) -> dict[str, str]:
    """The delegate's environment, as name -> value."""
    lines = (tmp_path / "probe" / "env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_exports_only_the_allowlisted_name(repo: Path, tmp_path: Path) -> None:
    (repo / ".env").write_text(ENV_TEXT)
    result = _run(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    seen = _seen(tmp_path)
    assert seen["TEST_DATABASE_URL"] == TEST_URL, "quotes stripped, spaces kept"
    assert seen["PRE_SHIP_ENV_NAMES"] == "TEST_DATABASE_URL"
    for name in ("GH_TOKEN", "ANTHROPIC_API_KEY", "ARCHIVER_DEV_DATABASE_URL"):
        assert name not in seen, name


def test_never_prints_a_value(repo: Path, tmp_path: Path) -> None:
    (repo / ".env").write_text(ENV_TEXT)
    result = _run(repo, tmp_path)
    for value in (TEST_URL, SECRET):
        assert value not in result.stdout + result.stderr


def test_no_env_file_warns_and_names_nothing(repo: Path, tmp_path: Path) -> None:
    """An exported but empty list is how the gate knows to write no stamp (#497)."""
    result = _run(repo, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "WARN: no env file" in result.stderr
    seen = _seen(tmp_path)
    assert seen["PRE_SHIP_ENV_NAMES"] == ""
    assert "TEST_DATABASE_URL" not in seen


def test_a_linked_worktree_reads_the_primary_checkouts_env(repo: Path, tmp_path: Path) -> None:
    """``.env`` is gitignored, so a worktree has none of its own (#497)."""
    (repo / ".env").write_text(ENV_TEXT)
    tree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feature", str(tree))
    result = _run(tree, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "WARN" not in result.stderr
    assert _seen(tmp_path)["TEST_DATABASE_URL"] == TEST_URL


def test_the_file_wins_over_an_inherited_value(repo: Path, tmp_path: Path) -> None:
    """The file wins over an inherited value, as in upstream's recipe."""
    (repo / ".env").write_text(ENV_TEXT)
    _run(repo, tmp_path, TEST_DATABASE_URL="postgresql:///archiver")
    assert _seen(tmp_path)["TEST_DATABASE_URL"] == TEST_URL


def test_exit_code_and_arguments_reach_through(repo: Path, tmp_path: Path) -> None:
    (repo / ".env").write_text(ENV_TEXT)
    result = _run(repo, tmp_path, "--help", FAKE_EXIT="1")
    assert result.returncode == 1
    assert (tmp_path / "probe" / "args").read_text() == "--help\n"


def test_a_missing_delegate_exits_2(repo: Path, tmp_path: Path) -> None:
    """An unpopulated submodule names the fix, not bash's generic error."""
    (repo / DELEGATE).unlink()
    result = _run(repo, tmp_path)
    assert result.returncode == 2
    assert "git submodule update --init --recursive" in result.stderr


def test_never_names_the_production_env_file() -> None:
    """Not behavioural, since a test cannot plant ``/etc/archiver/.env``: no line
    of code may name an ``/etc`` path (comments may, to say why)."""
    code = [line for line in WRAPPER.read_text().splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "/etc/" in line]


def test_delegates_through_the_skill_symlink() -> None:
    """The symlink is the stable interface; the vendor layout is not."""
    text = WRAPPER.read_text()
    assert f'DELEGATE="{DELEGATE}"' in text
    assert "skills-vendor" not in text


def test_outside_a_git_repository_exits_2(tmp_path: Path) -> None:
    """Tooling failure is 2 in the gate's exit table, not git's 128."""
    loose = tmp_path / "loose"
    (loose / "scripts").mkdir(parents=True)
    shutil.copy2(WRAPPER, loose / "scripts" / "pre-ship.sh")
    result = _run(loose, tmp_path, GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert result.returncode == 2
    assert "not inside a git repository" in result.stderr
