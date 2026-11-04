"""CI's test job checks out the one submodule the suite reads (#452 CR 9).

``scripts/lib/env.sh`` lifts ``load_env`` from the recipe in the vendored gate's
header, so the loader's tests need ``skills-vendor/gregoryfoster-skills``.
``actions/checkout`` fetches no submodules by default. The job fetches that one
alone, shallow (the repo is public), rather than ``submodules: true``, which
would also fetch ``obra-superpowers`` for nothing.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INIT = "git submodule update --init --depth 1 skills-vendor/gregoryfoster-skills"


def _test_steps() -> list[dict]:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]


def test_the_test_job_fetches_the_vendored_skills_before_pytest() -> None:
    steps = _test_steps()
    runs = [step.get("run", "") for step in steps]
    init = next(i for i, run in enumerate(runs) if INIT in run)
    first_pytest = next(i for i, run in enumerate(runs) if run.startswith("uv run pytest"))
    assert init < first_pytest


def test_the_checkout_itself_fetches_no_submodules() -> None:
    checkout = next(s for s in _test_steps() if s.get("uses", "").startswith("actions/checkout@"))
    assert "submodules" not in checkout.get("with", {})
