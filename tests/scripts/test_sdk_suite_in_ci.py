"""CI must run the ``archiver-client`` SDK's own pytest suite (archiver#248).

The root ``testpaths = ["tests"]`` never reaches ``clients/python/tests/``, and
``client-drift`` only diffs the regenerated tree against the snapshot. For
months nothing ran the SDK suite: fixtures went stale behind #150's required
``watch_spec``, and ``__version__`` sat at 5.0.0 through seven SDK releases,
while the test written to catch exactly that failed unwatched.

The suite runs inside ``client-drift``, from ``clients/python`` so it resolves
the SDK's own lockfile and pinned toolchain rather than the service's.
"""

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _client_drift_steps() -> list[dict]:
    workflow = yaml.safe_load(_CI.read_text())
    return workflow["jobs"]["client-drift"]["steps"]


def test_client_drift_runs_the_sdk_suite():
    runs = [
        step
        for step in _client_drift_steps()
        if step.get("working-directory") == "clients/python"
        and step.get("run", "").split()[:3] == ["uv", "run", "pytest"]
    ]
    assert len(runs) == 1, "client-drift must run `uv run pytest` in clients/python"
