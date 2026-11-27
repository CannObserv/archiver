"""The workflows pin their cache behaviour, and ci.yml its runner, on purpose (#192).

**The cache.** setup-uv v9 flipped ``prune-cache`` to ``false`` (v5's
``action.yml`` defaults it ``true``). Unpruned, the uv cache the lint and test
jobs save holds co-core unpacked from the private co-pypi index, and archiver is
public: a fork's pull request can restore a cache saved on ``main``. Dependabot
moves setup-uv past v9 with CI green, so the default would flip silently.
``uv cache prune --ci`` drops every pre-built wheel, co-core's included, so
every setup-uv step that saves a cache, in every workflow, states it; one with
``enable-cache: false`` saves none (audit.yml, #420). It keeps a wheel *built from
source*, so the prune covers co-core only while uv.lock pins it to a wheel:
tests/test_dependency_index.py holds that premise (#498). Ported from
CannObserv/broker#88.

**The runner.** ``ubuntu-24.04``, not ``ubuntu-latest``: CI matches the deploy
host's distro. ``ubuntu-latest`` moves to 26.04 on GitHub's schedule, between
2026-10-19 and 2026-11-19 per actions/runner-images#14748. When the host moves,
CI moves with it: on the host, ``test_runner_image_matches_the_host`` fails
until it does.

**The Node.** setup-node's ``node-version`` is a bare major, the host's own
(#428): ``pre-ship.sh`` runs ``npm test`` on the host's Node before every push,
and CI runs it again, so the two run one major. Dependabot moves setup-node's
``uses:`` ref, never its ``with:`` input, so nothing else would move it. When
the host moves, ``test_ci_node_matches_the_host`` fails on it until CI does.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.deploy.live_release import LIVE

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
OS_RELEASE = Path("/etc/os-release")


def _jobs(workflow: Path = CI) -> dict[str, dict]:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]


def _setup_uv_steps() -> list[dict]:
    """Every setup-uv step in every workflow: a new one saves a cache too."""
    return [
        step
        for workflow in sorted(CI.parent.glob("*.y*ml"))
        for job in _jobs(workflow).values()
        for step in job.get("steps", [])
        if step.get("uses", "").split("@")[0] == "astral-sh/setup-uv"
    ]


def _unpruned(steps: list[dict]) -> list[dict]:
    """The steps that save a cache without pruning it. ``enable-cache: false``
    saves none, so it has nothing to prune (audit.yml, #420); any other value,
    or none, saves one."""
    withs = [step.get("with", {}) for step in steps]
    return [
        w for w in withs if w.get("enable-cache") is not False and w.get("prune-cache") is not True
    ]


def test_every_setup_uv_step_prunes_the_cache_it_saves() -> None:
    """co-core's private source stays out of a public repo's Actions cache."""
    steps = _setup_uv_steps()
    assert steps, "no setup-uv step found in .github/workflows/: the derivation broke"
    bad = _unpruned(steps)
    assert not bad, f"setup-uv steps that save a cache without `prune-cache: true`: {bad}"


@pytest.mark.parametrize(
    ("with_", "unpruned"),
    [
        ({"enable-cache": True, "prune-cache": True}, False),
        ({"enable-cache": True}, True),
        ({}, True),
        ({"enable-cache": "auto"}, True),
        ({"enable-cache": False}, False),
        ({"enable-cache": "false"}, True),
    ],
)
def test_only_a_step_that_saves_nothing_skips_the_prune(with_: dict, unpruned: bool) -> None:
    """setup-uv defaults ``enable-cache`` to ``auto`` (on, on GitHub's runners), so
    only an explicit YAML ``false`` exempts a step; a quoted ``"false"`` is a
    string to YAML and to this check, and fails safe."""
    assert bool(_unpruned([{"with": with_}])) is unpruned


def _runners() -> set[str]:
    return {job["runs-on"] for job in _jobs().values()}


def test_ci_runs_on_one_pinned_image() -> None:
    runners = _runners()
    assert len(runners) == 1, runners
    assert not runners.pop().endswith("-latest")


def _os_version_id(os_release: Path) -> str:
    found = re.search(r'^VERSION_ID="?([^"\n]+)"?$', os_release.read_text(), re.MULTILINE)
    assert found, f"{os_release} names no VERSION_ID"
    return found[1]


def test_runner_image_matches_the_host() -> None:
    if not LIVE.is_symlink():
        pytest.skip(f"{LIVE} absent: not the deploy host")
    assert _runners() == {f"ubuntu-{_os_version_id(OS_RELEASE)}"}


def test_os_version_id_reads_a_quoted_and_a_bare_value(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nVERSION_ID="26.04"\n')
    assert _os_version_id(os_release) == "26.04"
    os_release.write_text("VERSION_ID=24.04\n")
    assert _os_version_id(os_release) == "24.04"


def _setup_node_versions() -> list[str]:
    """Every setup-node step's ``node-version``, in every workflow."""
    return [
        str(step.get("with", {}).get("node-version"))
        for workflow in sorted(CI.parent.glob("*.y*ml"))
        for job in _jobs(workflow).values()
        for step in job.get("steps", [])
        if step.get("uses", "").split("@")[0] == "actions/setup-node"
    ]


def _node_major(version: str) -> str:
    found = re.fullmatch(r"v?(\d+)(?:\.\d+){0,2}", version.strip())
    assert found, f"not a Node version: {version!r}"
    return found[1]


def test_setup_node_pins_a_bare_major() -> None:
    versions = _setup_node_versions()
    assert versions, "no setup-node step: the JS lint and tests run nowhere"
    assert all(re.fullmatch(r"\d+", v) for v in versions), versions


def test_ci_node_matches_the_host() -> None:
    if not LIVE.is_symlink():
        pytest.skip(f"{LIVE} absent: not the deploy host")
    node = shutil.which("node")
    assert node, "the deploy host has no node: pre-ship.sh's npm test cannot run"
    host = subprocess.run([node, "--version"], capture_output=True, text=True, check=True)
    assert set(_setup_node_versions()) == {_node_major(host.stdout)}


def test_node_major_reads_a_release_and_a_bare_major() -> None:
    assert _node_major("v24.22.3\n") == "24"
    assert _node_major("24") == "24"
    with pytest.raises(AssertionError):
        _node_major("lts/*")
