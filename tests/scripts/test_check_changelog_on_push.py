"""Tests for ``scripts/check_changelog_on_push.sh``.

The script is wired as a pre-push hook (see ``.pre-commit-config.yaml``) and
reads git's pre-push stdin protocol — one line per ref being pushed:

    <local_ref> <local_sha> <remote_ref> <remote_sha>

Each test builds a throwaway git repo in ``tmp_path``, creates commits with
controlled subjects, then invokes the script with synthetic stdin matching
the protocol. We assert exit code + stderr.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_changelog_on_push.sh"
ZERO = "0" * 40
MAIN = "refs/heads/main"
FEATURE = "refs/heads/feature"


def _git(repo: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
        **kwargs,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Bare-bones git repo with `main` as the initial branch and identity set."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def commit(repo: Path, subject: str, files: dict[str, str] | None = None) -> str:
    """Create a commit with the given subject, returning the new HEAD SHA.

    ``files`` maps relative path → contents. Defaults to a placeholder file
    derived from the subject so each commit produces a non-empty diff.
    """
    payload = files if files is not None else {"placeholder.txt": subject}
    for name, content in payload.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", subject, "--no-verify")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def run_script(repo: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repo,
        input=stdin,
        text=True,
        capture_output=True,
    )


def push_line(local_sha: str, remote_sha: str, ref: str = MAIN) -> str:
    """Build one line of git's pre-push stdin protocol."""
    return f"{ref} {local_sha} {ref} {remote_sha}\n"


# ---------------------------------------------------------------------------
# Happy paths


def test_non_feat_fix_range_passes(repo: Path) -> None:
    """`chore:` and `docs:` commits don't require CHANGELOG.md."""
    base = commit(repo, "chore: initial")
    head = commit(repo, "docs: tweak readme")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_fix_with_changelog_passes(repo: Path) -> None:
    """A `fix:` commit that touches CHANGELOG.md satisfies the rule."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "fix(sdk): squash an off-by-one",
        {"src/thing.py": "x = 1\n", "CHANGELOG.md": "## v1.2.3\n"},
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_changelog_in_later_commit_in_range_passes(repo: Path) -> None:
    """Multi-commit range: feat without CHANGELOG, then docs adds CHANGELOG → pass."""
    base = commit(repo, "chore: seed")
    commit(repo, "feat(api): new endpoint")
    head = commit(repo, "docs: log it", {"CHANGELOG.md": "## v1.3.0\n"})

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Failure paths


def test_feat_without_changelog_fails(repo: Path) -> None:
    """`feat:` without a CHANGELOG.md change in range exits 1 and names the offender."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat(sdk): new public method")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "feat(sdk): new public method" in result.stderr


def test_issue_prefix_recognized(repo: Path) -> None:
    """`#42 fix: ...` matches the optional issue-prefix pattern."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "#42 fix: addresses something")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "#42 fix" in result.stderr


def test_feat_bang_marker_triggers(repo: Path) -> None:
    """Conventional Commits breaking-change marker (`feat!:`) is matched."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat!: drop legacy field")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "feat!: drop legacy field" in result.stderr


def test_feat_scope_bang_marker_triggers(repo: Path) -> None:
    """`feat(scope)!:` — both scope and bang — is matched."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat(api)!: rename resource")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "feat(api)!: rename resource" in result.stderr


def test_fix_bang_marker_triggers(repo: Path) -> None:
    """`fix!:` is matched; pinned alongside the feat!: case so the alternation
    in the regex can't silently regress for one branch but not the other."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "fix!: incompatible default-value change")

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "fix!: incompatible default-value change" in result.stderr


# ---------------------------------------------------------------------------
# Skip paths (script exits 0 without enforcing)


def test_non_main_ref_skipped(repo: Path) -> None:
    """Pushing a feat to a non-main ref bypasses the check entirely."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat(sdk): new public method")

    result = run_script(repo, push_line(head, base, ref=FEATURE))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_new_main_ref_skipped(repo: Path) -> None:
    """Pushing a brand-new `main` (remote_sha=ZERO) skips with a clear message."""
    commit(repo, "chore: seed")
    head = commit(repo, "feat(sdk): new public method")

    result = run_script(repo, push_line(head, ZERO))

    assert result.returncode == 0, result.stderr
    assert "new ref to refs/heads/main" in result.stderr
    # Specifically: must NOT have run the check and emitted an ERROR.
    assert "ERROR" not in result.stderr


def test_branch_delete_skipped(repo: Path) -> None:
    """A branch-delete push (local_sha=ZERO) is a no-op."""
    seed = commit(repo, "chore: seed")

    result = run_script(repo, push_line(ZERO, seed))

    assert result.returncode == 0, result.stderr


def test_empty_stdin_noop(repo: Path) -> None:
    """No input lines → script exits 0 cleanly."""
    result = run_script(repo, "")

    assert result.returncode == 0, result.stderr
