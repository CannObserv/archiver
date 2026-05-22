"""Tests for ``scripts/check_changelog_on_push.sh``.

The script is wired as a pre-push hook (see ``.pre-commit-config.yaml``) and
reads git's pre-push stdin protocol — one line per ref being pushed:

    <local_ref> <local_sha> <remote_ref> <remote_sha>

Each test builds a throwaway git repo in ``tmp_path``, creates commits with
controlled file trees, then invokes the script with synthetic stdin matching
the protocol. We assert exit code + stderr.

Enforcement logic: a CHANGELOG.md entry is required when any changed file
falls under a contract-visible path (mirrors ``scripts/check_changelog_lib.sh``):
  - ``alembic/versions/``   deployed DB migrations
  - ``src/api/routes/``     HTTP API surface
  - ``src/api/schemas/``    Pydantic request/response contract models
  - ``clients/python/``     archiver-client SDK
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
    so each commit produces a non-empty diff.
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
# Happy paths — non-trigger paths never require a CHANGELOG entry


def test_non_trigger_paths_pass(repo: Path) -> None:
    """Internal-only file changes do not require CHANGELOG.md."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "fix: lint tweak",
        {
            "src/dashboard/static/dashboard.js": "// fixed\n",
            "src/core/simhash.py": "# patched\n",
            "tests/test_foo.py": "# test\n",
        },
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_trigger_path_with_changelog_passes(repo: Path) -> None:
    """A trigger-path change that also touches CHANGELOG.md satisfies the rule."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "feat: new endpoint",
        {
            "src/api/routes/info_items.py": "# new route\n",
            "CHANGELOG.md": "## v1.2.3\n",
        },
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_changelog_in_later_commit_in_range_passes(repo: Path) -> None:
    """Multi-commit range: trigger path first, CHANGELOG added in later commit → pass."""
    base = commit(repo, "chore: seed")
    commit(repo, "feat: new endpoint", {"src/api/routes/new.py": "# route\n"})
    head = commit(repo, "docs: log it", {"CHANGELOG.md": "## v1.3.0\n"})

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_dashboard_only_change_passes(repo: Path) -> None:
    """Dashboard UX changes are never contract-visible and never require CHANGELOG."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "fix: dashboard UX",
        {
            "src/dashboard/routes/settings.py": "# tweak\n",
            "src/dashboard/templates/base.html": "<html/>\n",
        },
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


def test_alembic_env_py_not_a_trigger(repo: Path) -> None:
    """Alembic root files (env.py, script.py.mako) are not migration files."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "chore: update alembic config",
        {"alembic/env.py": "# updated\n"},
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Failure paths — trigger-path changes without CHANGELOG exit 1


def test_api_route_change_without_changelog_fails(repo: Path) -> None:
    """A change to an API route file requires CHANGELOG.md."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat: new route", {"src/api/routes/info_items.py": "# new\n"})

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "src/api/routes/info_items.py" in result.stderr


def test_api_schema_change_without_changelog_fails(repo: Path) -> None:
    """A change to a Pydantic schema file requires CHANGELOG.md."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "fix: remove deprecated field",
        {"src/api/schemas/info_item.py": "# changed\n"},
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "src/api/schemas/info_item.py" in result.stderr


def test_alembic_migration_without_changelog_fails(repo: Path) -> None:
    """A new alembic migration requires CHANGELOG.md."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat: add column", {"alembic/versions/abc123_add_col.py": "# migration\n"})

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "alembic/versions/abc123_add_col.py" in result.stderr


def test_sdk_change_without_changelog_fails(repo: Path) -> None:
    """A change under clients/python/ requires CHANGELOG.md."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "feat: new sdk method",
        {"clients/python/src/archiver_client/api.py": "# sdk\n"},
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "clients/python/src/archiver_client/api.py" in result.stderr


def test_error_message_lists_matched_trigger_paths(repo: Path) -> None:
    """The error message enumerates the matched trigger-path files."""
    base = commit(repo, "chore: seed")
    head = commit(
        repo,
        "feat: dual trigger",
        {
            "src/api/routes/info_items.py": "# route\n",
            "alembic/versions/abc.py": "# migration\n",
            "src/dashboard/static/app.js": "// internal\n",
        },
    )

    result = run_script(repo, push_line(head, base))

    assert result.returncode == 1
    assert "src/api/routes/info_items.py" in result.stderr
    assert "alembic/versions/abc.py" in result.stderr
    # dashboard file should NOT appear in the trigger list
    assert "app.js" not in result.stderr


# ---------------------------------------------------------------------------
# Skip paths (script exits 0 without enforcing)


def test_non_main_ref_skipped(repo: Path) -> None:
    """Pushing a trigger-path change to a non-main ref bypasses the check."""
    base = commit(repo, "chore: seed")
    head = commit(repo, "feat: new route", {"src/api/routes/foo.py": "# route\n"})

    result = run_script(repo, push_line(head, base, ref=FEATURE))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_new_main_ref_skipped(repo: Path) -> None:
    """Pushing a brand-new `main` (remote_sha=ZERO) skips with a clear message."""
    commit(repo, "chore: seed")
    head = commit(repo, "feat: new route", {"src/api/routes/foo.py": "# route\n"})

    result = run_script(repo, push_line(head, ZERO))

    assert result.returncode == 0, result.stderr
    assert "new ref to refs/heads/main" in result.stderr
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
