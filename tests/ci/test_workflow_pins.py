"""ci.yml pins its runner and its cache behaviour on purpose (#192).

**The cache.** setup-uv v9 flipped ``prune-cache`` to ``false`` (v5's
``action.yml`` defaults it ``true``). Unpruned, the uv cache the lint and test
jobs save holds co-core unpacked from the private wheelhouse, and archiver is
public: a fork's pull request can restore a cache saved on ``main``. Dependabot
moves setup-uv past v9 with CI green, so the default would flip silently.
``uv cache prune --ci`` drops every pre-built wheel, co-core's included, so
each step states it. It keeps a wheel *built from source*, so the prune covers
co-core only while uv.lock pins it to a wheel: the lock check below holds that
premise. Ported from CannObserv/broker#88.

**The runner.** ``ubuntu-24.04``, not ``ubuntu-latest``: CI matches the deploy
host's distro. ``ubuntu-latest`` moves to 26.04 on GitHub's schedule, between
2026-10-19 and 2026-11-19 per actions/runner-images#14748. When the host moves,
CI moves with it: on the host, ``test_runner_image_matches_the_host`` fails
until it does.
"""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

from tests.deploy.live_release import LIVE

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LOCK = REPO_ROOT / "uv.lock"
OS_RELEASE = Path("/etc/os-release")


def _jobs() -> dict[str, dict]:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _setup_uv_steps() -> list[dict]:
    return [
        step
        for job in _jobs().values()
        for step in job.get("steps", [])
        if step.get("uses", "").split("@")[0] == "astral-sh/setup-uv"
    ]


def test_every_setup_uv_step_prunes_the_cache_it_saves() -> None:
    """co-core's private source stays out of a public repo's Actions cache."""
    steps = _setup_uv_steps()
    assert steps, "no setup-uv step found in ci.yml: the derivation broke"
    bad = [s.get("with", {}) for s in steps if s.get("with", {}).get("prune-cache") is not True]
    assert not bad, f"setup-uv steps without `prune-cache: true`: {bad}"


def _wheelhouse_packages_without_a_wheel(lock: Path) -> list[str]:
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    return [
        p["name"]
        for p in packages
        if p.get("source", {}).get("registry") == ".wheelhouse" and not p.get("wheels")
    ]


def test_every_wheelhouse_package_is_locked_to_a_wheel() -> None:
    """The prune's premise: a package installed from its wheel is pruned."""
    assert _wheelhouse_packages_without_a_wheel(LOCK) == []


def test_wheel_check_fails_on_an_sdist_only_lock(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "co-core"\nversion = "9.9.9"\n'
        'source = { registry = ".wheelhouse" }\n'
        'sdist = { path = "co_core-9.9.9.tar.gz" }\n'
    )
    assert _wheelhouse_packages_without_a_wheel(lock) == ["co-core"]


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
