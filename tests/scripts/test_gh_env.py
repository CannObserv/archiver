"""``GH_TOKEN`` reaches ``gh`` from ``.env``, read as data (#466; gregoryfoster/skills#576).

The same approach as CannObserv/processor#115, and a local replica of
gregoryfoster/skills#334's planned ``using-github-cli`` hook until it ships. Two
consumers:

- the agent's Bash calls, through ``.claude/hooks/gh-env.sh`` and ``$CLAUDE_ENV_FILE``;
- the refresh hook, whose ``merge_mode pr`` path opens its PR with ``gh``. SessionStart
  hooks run in parallel, so no export reaches it. Its registration reads the token
  itself, through ``scripts/env-value.sh``.

``scripts/env-value.sh`` parses with ``scripts/lib/env.sh``, so ``load_env`` stays the
only parser (#452). ``.env`` is never executed, the token is never printed, and the
hook always exits 0.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV_VALUE = ROOT / "scripts" / "env-value.sh"
GH_ENV = ROOT / ".claude" / "hooks" / "gh-env.sh"
SETTINGS = ROOT / ".claude" / "settings.json"
# What env-value.sh needs beside it: the library and the recipe it lifts load_env from.
SUPPORT = (
    ROOT / "scripts" / "lib" / "env.sh",
    ROOT / "skills" / "shipping-work" / "scripts" / "pre-ship.sh",
)
# Shell metacharacters, both quotes and a command substitution: %q must carry all.
NASTY = 'gh\'p_"a b" $(touch pwned) ;x`y`'


def _value(env: Path, name: str = "GH_TOKEN") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(ENV_VALUE), name, str(env)],
        capture_output=True,
        text=True,
        cwd=env.parent,
        timeout=30,
    )


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("GH_TOKEN=abc\n", "abc"),
        ("export GH_TOKEN=abc\n", "abc"),
        ('GH_TOKEN="a b"\n', "a b"),
        ("GH_TOKEN='a b'\n", "a b"),
        ("GH_TOKEN=abc\r\n", "abc"),
        ("GH_TOKEN=old\nGH_TOKEN=new\n", "new"),
        ("GH_TOKEN_BROKER=no\nGH_TOKEN=yes\nGH_TOKEN_X=no\n", "yes"),
        ("# GH_TOKEN=commented\nGH_TOKEN=live\n", "live"),
    ],
)
def test_env_value_reads_one_name(tmp_path: Path, text: str, want: str) -> None:
    env = tmp_path / ".env"
    env.write_text(text)
    out = _value(env)
    assert (out.returncode, out.stdout) == (0, want), out.stderr


def test_env_value_never_executes_the_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("touch executed\nGH_TOKEN=$(touch substituted)\n")
    out = _value(env)
    assert out.stdout == "$(touch substituted)"
    assert not (tmp_path / "executed").exists()
    assert not (tmp_path / "substituted").exists()


@pytest.mark.parametrize("text", [None, "OTHER=1\n", "GH_TOKEN_BROKER=x\n"])
def test_env_value_without_the_name_prints_nothing(tmp_path: Path, text: str | None) -> None:
    env = tmp_path / ".env"
    if text is not None:
        env.write_text(text)
    out = _value(env)
    assert (out.returncode, out.stdout) == (1, "")


def test_env_value_ignores_an_inherited_value(tmp_path: Path) -> None:
    """The file's value or nothing: an exported GH_TOKEN is not echoed back."""
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n")
    out = subprocess.run(
        ["bash", str(ENV_VALUE), "GH_TOKEN", str(env)],
        capture_output=True,
        text=True,
        env={**os.environ, "GH_TOKEN": "inherited"},
        timeout=30,
    )
    assert (out.returncode, out.stdout) == (1, "")


@pytest.mark.parametrize("name", ["GH_*", "1BAD", "A-B", ""])
def test_env_value_refuses_a_name_that_is_not_one(tmp_path: Path, name: str) -> None:
    """load_env_only takes globs; env-value.sh takes exactly one name."""
    env = tmp_path / ".env"
    env.write_text("GH_TOKEN=t\nGH_X=u\n")
    out = _value(env, name)
    assert (out.returncode, out.stdout) == (2, "")


def _project(tmp_path: Path, env_text: str | None) -> Path:
    """A git checkout holding the two scripts and their support, and optionally an ``.env``."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for src in (ENV_VALUE, GH_ENV, *SUPPORT):
        dst = repo / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)  # follows the skills/ symlink: a file, not a dangling link
    (repo / ".gitignore").write_text(".env\n")
    if env_text is not None:
        (repo / ".env").write_text(env_text)
    return repo


def _fake_gh(tmp_path: Path, version: str) -> str:
    bin_dir = tmp_path / f"bin-{version}"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "gh version {version} (2026-01-01)"\n')
    gh.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def _hook(
    project: Path, tmp_path: Path, *, env_file: bool = True, extra: dict | None = None
) -> tuple[subprocess.CompletedProcess, Path]:
    target = tmp_path / "claude-env"
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    env |= {"CLAUDE_PROJECT_DIR": str(project), "PATH": _fake_gh(tmp_path, "2.101.0")}
    if env_file:
        env["CLAUDE_ENV_FILE"] = str(target)
    else:
        env.pop("CLAUDE_ENV_FILE", None)
    env |= extra or {}
    out = subprocess.run(
        ["bash", str(project / GH_ENV.relative_to(ROOT))],
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
        timeout=30,
    )
    return out, target


def _exported(target: Path) -> str:
    """What a shell that sources the env file sees, as the harness does."""
    script = f'. {shlex.quote(str(target))}; printf %s "$GH_TOKEN"'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout


def test_hook_exports_the_token_exactly_and_never_prints_it(tmp_path: Path) -> None:
    project = _project(tmp_path, f"GH_TOKEN={NASTY}\n")
    out, target = _hook(project, tmp_path)
    assert out.returncode == 0, out.stderr
    assert _exported(target) == NASTY
    assert "gh'p_" not in out.stdout + out.stderr
    assert not (project / "pwned").exists()


def test_hook_exports_only_gh_token(tmp_path: Path) -> None:
    """Cross-repo GH_TOKEN_<REPO> and every other name stay per call (#452)."""
    project = _project(tmp_path, "GH_TOKEN=t\nGH_TOKEN_BROKER=b\nANTHROPIC_API_KEY=k\n")
    out, target = _hook(project, tmp_path)
    assert out.returncode == 0, out.stderr
    text = target.read_text()
    assert text.count("export ") == 1
    assert text.startswith("export GH_TOKEN=")


def test_hook_reads_the_primary_checkouts_env_from_a_worktree(tmp_path: Path) -> None:
    """``.env`` is git-ignored, so a linked worktree has none of its own."""
    project = _project(tmp_path, "GH_TOKEN=primary\n")
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)
    git_id = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "-C", str(project), *git_id, "commit", "-qm", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(project), "worktree", "add", "-q", str(wt)], check=True)
    out, target = _hook(wt, tmp_path)
    assert out.returncode == 0, out.stderr
    assert _exported(target) == "primary"


def test_hook_leaves_a_set_token_alone(tmp_path: Path) -> None:
    project = _project(tmp_path, "GH_TOKEN=from-file\n")
    out, target = _hook(project, tmp_path, extra={"GH_TOKEN": "from-env"})
    assert out.returncode == 0
    assert not target.exists()


def test_hook_says_when_env_has_no_token(tmp_path: Path) -> None:
    project = _project(tmp_path, "OTHER=1\n")
    out, target = _hook(project, tmp_path)
    assert out.returncode == 0
    assert "no GH_TOKEN" in out.stdout
    assert not target.exists()


def test_hook_says_when_the_parser_is_missing(tmp_path: Path) -> None:
    """No recipe (submodules not checked out) is not the same as no token."""
    project = _project(tmp_path, "GH_TOKEN=t\n")
    (project / SUPPORT[1].relative_to(ROOT)).unlink()
    out, target = _hook(project, tmp_path)
    assert out.returncode == 0
    assert "could not read" in out.stdout
    assert "no GH_TOKEN" not in out.stdout
    assert not target.exists()


def test_hook_without_claude_env_file_prints_the_manual_export(tmp_path: Path) -> None:
    """anthropics/claude-code#15840: the variable can be unset."""
    project = _project(tmp_path, "GH_TOKEN=secret-value\n")
    out, _ = _hook(project, tmp_path, env_file=False)
    assert out.returncode == 0
    assert "scripts/env-value.sh GH_TOKEN" in out.stdout
    assert "secret-value" not in out.stdout + out.stderr


@pytest.mark.parametrize(
    ("version", "warns"), [("2.9.0", True), ("2.77.9", True), ("2.78.0", False), ("2.101.0", False)]
)
def test_hook_warns_below_the_gh_floor(tmp_path: Path, version: str, warns: bool) -> None:
    """cli/cli#11514, fixed in 2.78.0; compared as versions (2.9.0 < 2.78.0), not strings."""
    project = _project(tmp_path, "GH_TOKEN=t\n")
    out, _ = _hook(project, tmp_path, extra={"PATH": _fake_gh(tmp_path, version)})
    assert out.returncode == 0
    assert ("2.78.0" in out.stdout) is warns, out.stdout


def test_hook_warns_when_gh_is_missing(tmp_path: Path) -> None:
    project = _project(tmp_path, "GH_TOKEN=t\n")
    out, target = _hook(project, tmp_path, extra={"GH_ENV_GH": "gh-not-installed"})
    assert out.returncode == 0
    assert "not found" in out.stdout
    assert _exported(target) == "t"


def _session_start() -> list[dict]:
    return [
        h for g in json.loads(SETTINGS.read_text())["hooks"]["SessionStart"] for h in g["hooks"]
    ]


def test_gh_env_is_registered_once() -> None:
    entries = [h for h in _session_start() if h["command"].endswith("# gh-env")]
    assert len(entries) == 1, entries
    assert ".claude/hooks/gh-env.sh" in entries[0]["command"]


# Byte-identical to processor's registration (CannObserv/processor 8dc2a5d8d6), the
# shape gregoryfoster/skills#576 reports install-refresh.sh --check accepts.
REFRESH_COMMAND = (
    'GH_TOKEN="${GH_TOKEN:-$(bash "${CLAUDE_PROJECT_DIR:-.}/scripts/env-value.sh" GH_TOKEN)}" '
    'bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/skills-submodule-update.sh"'
)


def test_the_refresh_registration_matches_the_cohort_shape() -> None:
    (entry,) = [h for h in _session_start() if "skills-submodule-update.sh" in h["command"]]
    assert entry["command"] == REFRESH_COMMAND


def test_the_refresh_registration_hands_its_hook_the_token(tmp_path: Path) -> None:
    """The registered command, run as the harness runs it, against a stand-in hook."""
    (entry,) = [h for h in _session_start() if "skills-submodule-update.sh" in h["command"]]
    project = _project(tmp_path, f"GH_TOKEN={NASTY}\n")
    stand_in = project / ".claude" / "hooks" / "skills-submodule-update.sh"
    stand_in.write_text('#!/usr/bin/env bash\nprintf %s "$GH_TOKEN" > "$CLAUDE_PROJECT_DIR/seen"\n')
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    subprocess.run(["bash", "-c", entry["command"]], env=env, cwd=project, check=True, timeout=30)
    assert (project / "seen").read_text() == NASTY
    assert not (project / "pwned").exists()
