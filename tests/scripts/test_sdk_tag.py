"""Tests for ``scripts/sdk_tag.py``, the ``sdk-v<version>`` release tags (archiver#409).

A consumer off this VM pins ``archiver-client`` by git tag. A tag marks the
commit on ``main``'s first-parent line where ``clients/python/pyproject.toml``'s
version changes, which is the PR's merge commit (D1). ``tag`` makes it,
``check`` is the CI gate that every release since the floor carries one.

Each test builds a bare "origin" and a clone in ``tmp_path``, lands versions
through ``--no-ff`` merges as GitHub does, and runs the script against them.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sdk_tag.py"
PYPROJECT = "clients/python/pyproject.toml"
FLOOR = "5.19.0"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def _pyproject(version: str) -> str:
    return f'[project]\nname = "archiver-client"\nversion = "{version}"\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone of a bare origin, on ``main``, with SDK 5.18.0 pushed."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    for key, value in (
        ("user.email", "test@example.com"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        _git(work, "config", key, value)
    _git(work, "switch", "-q", "-c", "main")
    _commit(work, "base", {PYPROJECT: _pyproject("5.18.0")})
    _git(work, "push", "-q", "origin", "main")
    return work


def _commit(repo: Path, subject: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "--no-verify", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


def _land(repo: Path, branch: str, commits: list[dict[str, str]]) -> tuple[list[str], str]:
    """Merge ``branch`` into main with ``--no-ff`` and push: (branch SHAs, merge SHA)."""
    _git(repo, "switch", "-q", "-c", branch, "main")
    shas = [_commit(repo, f"{branch} {i}", files) for i, files in enumerate(commits)]
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "--no-verify", "-m", f"Merge {branch}", branch)
    _git(repo, "push", "-q", "origin", "main")
    return shas, _git(repo, "rev-parse", "HEAD")


def _bump(repo: Path, branch: str, version: str) -> tuple[str, str]:
    """Land a PR that bumps the SDK, then a CR fix to its code: (bump SHA, merge SHA)."""
    shas, merge = _land(
        repo,
        branch,
        [
            {PYPROJECT: _pyproject(version)},
            {"clients/python/src/archiver_client/client.py": f"# fixed in {version}\n"},
        ],
    )
    return shas[0], merge


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _remote_tags(repo: Path) -> str:
    return _git(repo, "ls-remote", "--tags", "origin")


def test_tag_marks_the_merge_commit_not_the_bump_commit(repo: Path) -> None:
    bump, merge = _bump(repo, "release", FLOOR)
    result = run(repo, "tag", "--push")
    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", f"sdk-v{FLOOR}^{{commit}}") == merge != bump
    assert _git(repo, "cat-file", "-t", f"sdk-v{FLOOR}") == "tag"  # annotated
    assert f"{merge}\trefs/tags/sdk-v{FLOOR}^{{}}" in _remote_tags(repo)


def test_tag_without_push_leaves_origin_untouched_and_names_the_push(repo: Path) -> None:
    _bump(repo, "release", FLOOR)
    result = run(repo, "tag")
    assert result.returncode == 0, result.stderr
    assert _git(repo, "tag", "--list", "sdk-v*") == f"sdk-v{FLOOR}"
    assert _remote_tags(repo) == ""
    assert f"git push origin refs/tags/sdk-v{FLOOR}" in result.stdout


def test_tag_is_idempotent(repo: Path) -> None:
    _bump(repo, "release", FLOOR)
    assert run(repo, "tag", "--push").returncode == 0
    again = run(repo, "tag", "--push")
    assert again.returncode == 0, again.stderr
    assert "already" in again.stdout


def test_tag_reads_origin_main_not_the_local_branch(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "unmerged")
    _commit(repo, "local only", {PYPROJECT: _pyproject("5.20.0")})
    _, merge = _bump(repo, "release", FLOOR)  # pushed from main
    _git(repo, "switch", "-q", "unmerged")
    assert run(repo, "tag").returncode == 0
    assert _git(repo, "tag", "--list", "sdk-v*") == f"sdk-v{FLOOR}"
    assert _git(repo, "rev-parse", f"sdk-v{FLOOR}^{{commit}}") == merge


def test_tag_tags_every_untagged_release_since_the_floor(repo: Path) -> None:
    _, first = _bump(repo, "a", FLOOR)
    _, second = _bump(repo, "b", "5.20.0")
    assert run(repo, "tag", "--push").returncode == 0
    assert _git(repo, "rev-parse", f"sdk-v{FLOOR}^{{commit}}") == first
    assert _git(repo, "rev-parse", "sdk-v5.20.0^{commit}") == second
    assert "sdk-v5.18.0" not in _remote_tags(repo)  # below the floor: never backfilled


def test_tag_refuses_to_move_a_tag_on_origin(repo: Path) -> None:
    bump, _ = _bump(repo, "release", FLOOR)
    _git(repo, "tag", "-a", f"sdk-v{FLOOR}", bump, "-m", "wrong commit")
    _git(repo, "push", "-q", "origin", f"refs/tags/sdk-v{FLOOR}")
    _git(repo, "tag", "-d", f"sdk-v{FLOOR}")
    result = run(repo, "tag", "--push")
    assert result.returncode == 1
    assert "never moved" in result.stderr
    assert f"{bump}\trefs/tags/sdk-v{FLOOR}^{{}}" in _remote_tags(repo)


def test_tag_refuses_a_local_tag_on_another_commit(repo: Path) -> None:
    bump, _ = _bump(repo, "release", FLOOR)
    _git(repo, "tag", "-a", f"sdk-v{FLOOR}", bump, "-m", "wrong commit")
    result = run(repo, "tag", "--push")
    assert result.returncode == 1
    assert _remote_tags(repo) == ""


def test_check_fails_on_an_untagged_release_and_names_the_fix(repo: Path) -> None:
    _bump(repo, "release", FLOOR)
    result = run(repo, "check", "origin/main")
    assert result.returncode == 1
    assert f"sdk-v{FLOOR}" in result.stderr
    assert "scripts/sdk_tag.py tag --push" in result.stderr
    assert "clients/python/README.md § Releases and tags" in result.stderr  # CR 2


def test_check_passes_once_tagged(repo: Path) -> None:
    _bump(repo, "release", FLOOR)
    assert run(repo, "tag", "--push").returncode == 0
    result = run(repo, "check", "origin/main")
    assert result.returncode == 0, result.stderr


def test_check_ignores_versions_below_the_floor(repo: Path) -> None:
    _land(repo, "older", [{PYPROJECT: _pyproject("5.18.1")}])
    assert run(repo, "check", "origin/main").returncode == 0


def test_check_on_the_bump_prs_base_stays_green(repo: Path) -> None:
    """The bump PR and its merge push check the base, whose release is tagged."""
    _bump(repo, "a", FLOOR)
    assert run(repo, "tag", "--push").returncode == 0
    base = _git(repo, "rev-parse", "origin/main")
    _bump(repo, "b", "5.20.0")
    assert run(repo, "check", base).returncode == 0
    assert run(repo, "check", "origin/main").returncode == 1  # the next PR is red


def test_check_fails_on_a_lightweight_tag(repo: Path) -> None:
    _, merge = _bump(repo, "release", FLOOR)
    _git(repo, "tag", f"sdk-v{FLOOR}", merge)
    _git(repo, "push", "-q", "origin", f"refs/tags/sdk-v{FLOOR}")
    result = run(repo, "check", "origin/main")
    assert result.returncode == 1
    assert "annotated" in result.stderr


def test_check_fails_on_a_tag_at_the_wrong_commit(repo: Path) -> None:
    bump, _ = _bump(repo, "release", FLOOR)
    _git(repo, "tag", "-a", f"sdk-v{FLOOR}", bump, "-m", "wrong commit")
    _git(repo, "push", "-q", "origin", f"refs/tags/sdk-v{FLOOR}")
    result = run(repo, "check", "origin/main")
    assert result.returncode == 1
    assert bump[:12] in result.stderr


def test_unknown_subcommand_is_a_usage_error(repo: Path) -> None:
    assert run(repo, "retag").returncode == 2


def test_ci_changelog_job_runs_the_check_against_the_base() -> None:
    """D3: the gate lives in the changelog job, which already fetches full history."""
    job = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"][
        "changelog"
    ]
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    runs = [s for s in job["steps"] if "scripts/sdk_tag.py check" in s.get("run", "")]
    assert len(runs) == 1
    step = runs[0]
    assert step["env"]["PR_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert step["env"]["PUSH_BEFORE_SHA"] == "${{ github.event.before }}"


def test_a_version_restored_by_a_revert_keeps_its_first_commit(repo: Path) -> None:
    """CR 1: a reverted bump brings a version back; its tag stays at its first commit."""
    _, first = _bump(repo, "a", FLOOR)
    _bump(repo, "b", "5.20.0")
    _land(repo, "revert-b", [{PYPROJECT: _pyproject(FLOOR)}])
    assert run(repo, "tag", "--push").returncode == 0
    assert _git(repo, "rev-parse", f"sdk-v{FLOOR}^{{commit}}") == first
    result = run(repo, "check", "origin/main")
    assert result.returncode == 0, result.stderr


def test_check_refuses_a_shallow_clone(repo: Path, tmp_path: Path) -> None:
    """CR 3: at a shallow boundary every commit would look like it set its version."""
    _bump(repo, "release", FLOOR)
    shallow = tmp_path / "shallow"
    origin = (tmp_path / "origin.git").as_uri()
    _git(tmp_path, "clone", "-q", "--depth", "1", origin, str(shallow))
    result = run(shallow, "check", "origin/main")
    assert result.returncode == 2
    assert "shallow" in result.stderr
