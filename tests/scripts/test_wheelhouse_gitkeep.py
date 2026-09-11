"""``.wheelhouse/.gitkeep`` must stay tracked, and ``.wheelhouse`` must stay a directory.

``pyproject.toml``'s ``[tool.uv] find-links`` names ``.wheelhouse``. uv reads
that on *every* invocation and errors if the path will not open, so the
directory has to exist at checkout, before anything has had a chance to
populate it. ``.gitignore`` carries ``.wheelhouse/*`` with ``!.wheelhouse/.gitkeep``
for exactly that reason (archiver#116), and spells the reasoning out beside it.

Nothing asserted it. Setting up a worktree, an agent replaced the directory with
a symlink to another checkout's copy to avoid re-downloading the wheels; the
tracked ``.gitkeep`` went with it and ``git add -A`` committed the symlink. The
local suite stayed green - the symlink resolved here - and lint, test and
client-drift all died in CI inside 40 seconds on ``Failed to read --find-links
directory``.

That asymmetry is the reason this file exists. A breakage invisible on the
machine that causes it and fatal on every other one is worth a test rather than
a convention, and the cost is one ``git ls-files``.
"""

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WHEELHOUSE = _ROOT / ".wheelhouse"
_GITKEEP = ".wheelhouse/.gitkeep"


def _tracked() -> set[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.splitlines())


def test_the_gitkeep_is_tracked():
    """Untracked, the find-links directory is absent on a fresh clone."""
    assert _GITKEEP in _tracked()


def test_the_gitkeep_is_a_regular_file():
    """A symlink here is what CI cannot follow; locally it resolves and hides."""
    path = _ROOT / _GITKEEP
    assert path.is_file() and not path.is_symlink()


def test_the_wheelhouse_is_a_real_directory():
    """Not a symlink to another checkout's: that is the shortcut that broke it."""
    assert _WHEELHOUSE.is_dir() and not _WHEELHOUSE.is_symlink()


def test_find_links_still_names_the_directory_this_guards():
    """If the config moves, these assertions guard a path nothing reads."""
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert ".wheelhouse" in pyproject
