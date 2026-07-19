"""Tests for ``scripts/check_version_lockstep.py``.

The lockstep checker keeps ``[project].version`` in ``pyproject.toml`` in
lockstep with the newest ``## vX.Y.Z`` heading in ``CHANGELOG.md`` (the drift
behind #85: pyproject 3.2.0 vs CHANGELOG 4.2.2). Here we unit-test the pure
parsing/comparison logic: heading extraction, pyproject parsing, and the
compare that decides pass/fail.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_version_lockstep.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_version_lockstep", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# --- newest_changelog_version -------------------------------------------------


def test_newest_heading_is_first_version_heading():
    text = (
        "# Changelog\n\n"
        "intro prose\n\n"
        "## v4.2.2 (2026-07-19)\n\n- [service] thing\n\n"
        "## v4.2.1 (2026-06-13)\n\n- [sdk] older thing\n"
    )
    assert mod.newest_changelog_version(text) == "4.2.2"


def test_heading_without_date_suffix_is_accepted():
    assert mod.newest_changelog_version("## v1.0.0\n") == "1.0.0"


def test_non_version_headings_are_skipped():
    text = "## Unreleased\n\n## v2.3.4 (2026-01-01)\n"
    assert mod.newest_changelog_version(text) == "2.3.4"


def test_no_version_heading_returns_none():
    assert mod.newest_changelog_version("# Changelog\n\nnothing here\n") is None


def test_version_mentioned_in_prose_is_not_a_heading():
    text = "Body mentions v9.9.9 inline.\n\n## v1.2.3 (2026-01-01)\n"
    assert mod.newest_changelog_version(text) == "1.2.3"


# --- pyproject_version ---------------------------------------------------------


def test_pyproject_version_parses_project_table(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "archiver"\nversion = "4.2.2"\n')
    assert mod.pyproject_version(pyproject) == "4.2.2"


# --- check ----------------------------------------------------------------------


def _repo(tmp_path: Path, pyproject_version: str, changelog_version: str | None) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "archiver"\nversion = "{pyproject_version}"\n'
    )
    heading = f"## v{changelog_version} (2026-07-19)\n" if changelog_version else ""
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n{heading}")
    return tmp_path


def test_check_passes_on_matching_versions(tmp_path: Path, capsys):
    root = _repo(tmp_path, "4.2.2", "4.2.2")
    assert mod.check(root) == 0
    assert "4.2.2" in capsys.readouterr().out


def test_check_fails_on_mismatch_with_both_versions_in_message(tmp_path: Path, capsys):
    root = _repo(tmp_path, "3.2.0", "4.2.2")
    assert mod.check(root) == 1
    err = capsys.readouterr().err
    assert "3.2.0" in err
    assert "4.2.2" in err
    assert "pyproject.toml" in err
    assert "CHANGELOG.md" in err


def test_check_fails_when_changelog_has_no_version_heading(tmp_path: Path, capsys):
    root = _repo(tmp_path, "4.2.2", None)
    assert mod.check(root) == 1
    assert "CHANGELOG.md" in capsys.readouterr().err


def test_real_repo_is_in_lockstep():
    """The repo itself must satisfy its own gate (self-consistency for #85)."""
    repo_root = Path(__file__).resolve().parents[2]
    assert mod.check(repo_root) == 0


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("## v10.20.30 (2027-12-31)", "10.20.30"),
        ("##   v0.0.1", None),  # malformed: extra spaces — not the convention
    ],
)
def test_heading_regex_edges(heading: str, expected: str | None):
    assert mod.newest_changelog_version(heading + "\n") == expected
