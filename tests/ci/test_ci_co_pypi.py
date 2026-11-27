"""CI's three syncing jobs read co-core from the co-pypi index (archiver#498).

``lint``, ``test`` and ``browser`` authenticate by Workload Identity Federation
as ``co-pypi-reader`` and ask for an access token (``token_format:
access_token``, a masked step output). That token goes to the ``uv sync`` step
alone, as ``UV_INDEX_CO_PYPI_USERNAME`` / ``_PASSWORD``: every later ``uv run``
finds the venv synced and downloads nothing, so no later step holds it. The
sync is ``--locked``: with a token present, an unlocked sync would re-lock
against the index instead of failing. ``client-drift`` and ``changelog`` sync
nothing private and get no ``id-token``. Ported from CannObserv/broker#144's
``ci.yml``.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SYNCING = ("lint", "test", "browser")
PAIR = ("UV_INDEX_CO_PYPI_USERNAME", "UV_INDEX_CO_PYPI_PASSWORD")
READER = "co-pypi-reader@co-gcs.iam.gserviceaccount.com"


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _auth(job: dict) -> dict:
    (step,) = [
        s for s in job["steps"] if s.get("uses", "").split("@")[0] == "google-github-actions/auth"
    ]
    return step


@pytest.mark.parametrize("name", SYNCING)
def test_the_job_mints_an_access_token_as_the_reader(name: str) -> None:
    job = _jobs()[name]
    assert job["permissions"]["id-token"] == "write"
    step = _auth(job)
    assert step["id"] == "auth"
    assert step["with"]["service_account"] == READER
    assert step["with"]["token_format"] == "access_token"


@pytest.mark.parametrize("name", SYNCING)
def test_the_pair_reaches_the_locked_sync_alone(name: str) -> None:
    job = _jobs()[name]
    assert not set(PAIR) & set(job.get("env", {})), "job-wide, every step would hold it"
    holders = [s for s in job["steps"] if set(PAIR) & set(s.get("env", {}))]
    (sync,) = holders
    assert sync["run"].startswith("uv sync --locked ")
    assert sync["env"] == {
        "UV_INDEX_CO_PYPI_USERNAME": "oauth2accesstoken",
        "UV_INDEX_CO_PYPI_PASSWORD": "${{ steps.auth.outputs.access_token }}",
    }
    steps = job["steps"]
    assert steps.index(_auth(job)) < steps.index(sync)


@pytest.mark.parametrize("name", SYNCING)
def test_no_step_syncs_a_wheelhouse(name: str) -> None:
    runs = " ".join(s.get("run", "") for s in _jobs()[name]["steps"])
    assert "wheelhouse" not in runs


@pytest.mark.parametrize("name", ["client-drift", "changelog"])
def test_a_job_that_syncs_nothing_private_gets_no_oidc(name: str) -> None:
    job = _jobs()[name]
    assert job.get("permissions", {}).get("id-token") != "write"
    assert not [s for s in job["steps"] if set(PAIR) & set(s.get("env", {}))]
