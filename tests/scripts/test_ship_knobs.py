"""The three ``.skills/`` knobs the unified ``shipping-work`` skill reads (#457 D3).

They replace what the retired ``shipping-work-python-fastapi`` and
``using-git-worktrees`` overrides said in prose:

- ``import-targets``: ``[project] name = "archiver"`` names no package (there is no
  ``archiver/`` or ``src/archiver/``), so without the knob the gate's import check
  is skipped with a note (gate-topology row 7).
- ``merge_mode``: ``pr``. Work lands here through a PR merged on GitHub, never a
  local merge to ``main``.
- ``deploy_command``: ``scripts/deploy.sh``. Without it Step 8 offers ``alembic
  upgrade head`` and ``systemctl restart archiver``, both wrong since #330:
  production runs releases, and a restart deploys nothing.

Upstream's readers check each knob only when a ship runs; these pin the values.
"""

from __future__ import annotations

import importlib
import os
import subprocess

from tests.scripts._skills_lists import REPO_ROOT, read_list_file

KNOBS = REPO_ROOT / ".skills"


def test_each_import_target_is_importable() -> None:
    """Imported, not just found: the gate executes the module, and so does this."""
    targets = read_list_file(KNOBS / "import-targets")
    assert targets, "no import target: the gate would skip its import check"
    for target in targets:
        importlib.import_module(target)


def test_merge_mode_is_pr() -> None:
    assert read_list_file(KNOBS / "merge_mode") == ("pr",)


def test_the_deploy_command_waits_on_the_tracked_deploy_script() -> None:
    """``setsid -w``: its own session, and its exit code is the deploy's. A bare
    ``setsid`` returns once the deploy has started (deploy-command.md)."""
    lines = read_list_file(KNOBS / "deploy_command")
    assert len(lines) == 1, "the knob takes one command line"
    words = lines[0].split()
    assert words[:2] == ["setsid", "-w"], words
    script = words[2]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", script],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert tracked.returncode == 0, f"{script} is not tracked"
    assert os.access(REPO_ROOT / script, os.X_OK), f"{script} is not executable"
