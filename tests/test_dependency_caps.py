"""Every runtime dependency carries an upper bound (#192).

The caps are the policy ``.github/dependabot.yml`` would serve once ``uv``
joins it: a bound sits one step below a wall, and crossing it takes a reviewed
diff. An uncapped specifier opts out of that silently, so a re-lock walks it
across a major nobody read. ``redis[hiredis]>=5`` was the one; co-core-aio's
``[bus]`` extra already held it ``<8``. ``[tool.uv.sources]`` entries carry no
specifier at all: their source pins them (a path, a git tag).
"""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent


def _uncapped(pyproject: dict) -> list[str]:
    sourced = set(pyproject.get("tool", {}).get("uv", {}).get("sources", {}))
    found = []
    for spec in pyproject["project"]["dependencies"]:
        req = Requirement(spec)
        if req.name in sourced:
            continue
        if not any(s.operator in {"<", "<=", "==", "~="} for s in req.specifier):
            found.append(spec)
    return found


def test_every_runtime_dependency_is_capped() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert _uncapped(pyproject) == [], "cap each runtime specifier below its next wall"


def test_the_check_flags_a_floor_only_specifier_and_spares_a_sourced_one() -> None:
    pyproject = {
        "project": {"dependencies": ["redis>=5", "httpx>=0.28,<1", "archiver-client"]},
        "tool": {"uv": {"sources": {"archiver-client": {"path": "clients/python"}}}},
    }
    assert _uncapped(pyproject) == ["redis>=5"]
