"""pytest's basetemp retention, the repo-side disk knob the host GC doesn't own (#440).

Each run of this suite leaves a ~160M tree in ``/tmp/pytest-of-<user>/pytest-N``,
and pytest's default keeps three. On a 30G root that sat at 86% (2026-11-13),
that's ~0.5G the host's disk GC can't reason about: only the repo knows which
of its trees are worth keeping. ``maintaining-host-disk``'s
``references/repo-knobs.md`` asks every cohort repo for the same two lines:
keep one run, and from it only the failed tests' directories. The host's
``alert_at_percent`` is then sized from the baseline plus one run's basetemp.
"""

import tomllib

from tests.scripts._skills_lists import REPO_ROOT

PYTEST_OPTIONS = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["tool"]["pytest"][
    "ini_options"
]


def test_keeps_one_runs_basetemp():
    """Only the newest run's basetemp stays on disk."""
    assert PYTEST_OPTIONS.get("tmp_path_retention_count") == 1


def test_keeps_only_failed_tests_directories():
    """A green run leaves nothing behind; a failing one keeps its evidence."""
    assert PYTEST_OPTIONS.get("tmp_path_retention_policy") == "failed"
