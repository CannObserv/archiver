"""CI runs the browser tier in a job of its own, on every PR and push (archiver#546).

Its own job, not a step in ``test``: it runs beside ``test`` rather than after it,
so it adds no wall time while it finishes first, and the ``browser`` group stays
out of every other job's sync. ``scripts/deploy.sh``'s gate needs no edit to
honour it: a run fails the gate on any job that did not pass, listed in
``CI_JOBS`` or not.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _runs(job: dict) -> list[str]:
    return [step.get("run", "") for step in job["steps"]]


def test_the_browser_job_has_a_time_limit() -> None:
    assert 0 < _jobs()["browser"]["timeout-minutes"] <= 20


def test_it_syncs_the_browser_group_installs_chromium_then_runs_the_tier() -> None:
    runs = _runs(_jobs()["browser"])
    sync = runs.index("uv sync --locked --group dev --group browser")
    install = runs.index("bash scripts/install_browser.sh --with-deps")
    tier = "uv run --group browser pytest"
    pytest_run = next(i for i, r in enumerate(runs) if r.startswith(tier))
    assert sync < install < pytest_run
    assert "-m browser" in runs[pytest_run]
    assert "tests/browser" in runs[pytest_run].split()


def test_it_has_its_own_test_database() -> None:
    job = _jobs()["browser"]
    assert job["services"]["postgres"]["env"]["POSTGRES_DB"] == "archiver_test"
    assert job["env"]["TEST_DATABASE_URL"].endswith("/archiver_test")


def test_no_other_job_syncs_the_browser_group() -> None:
    for name, job in _jobs().items():
        if name == "browser":
            continue
        assert not any("--group browser" in run for run in _runs(job)), name
