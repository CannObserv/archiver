"""The deployed build id (archiver#330 D8, CannObserv/status R10).

``scripts/deploy.sh`` builds each release from one pushed commit and writes
``REVISION`` (the commit's 12-character SHA) into the release root last. The
code reads it from the tree it runs from, so ``/health`` names the code that
is actually serving - not ``git describe --dirty`` of whatever the dev
checkout had checked out when the unit started.

``BUILD_ID`` is a transitional fallback: until the units run releases, the
unit's ``ExecStartPre`` stamp is the only id there is. ``None`` outside a
release and unstamped (a dev server, the test suite).
"""

import os
from functools import cache
from pathlib import Path

#: The release (or checkout) root: the project is installed editable, so this
#: module sits at ``<root>/src/core/``. ``resolve()`` follows ``live`` to the
#: physical release, so a later swap never changes what a process reports.
ROOT = Path(__file__).resolve().parents[2]


@cache
def _revision(root: Path) -> str:
    """``root``'s ``REVISION``, read once: a process's release never changes under it.

    Cached because ``/health`` is an async handler, and a file read per request
    would block its event loop.
    """
    try:
        return (root / "REVISION").read_text().strip()
    except FileNotFoundError:
        return ""


def build_id(root: Path | None = None) -> str | None:
    """The release's ``REVISION``, else the unit's ``BUILD_ID``, else None."""
    return _revision(root or ROOT) or os.environ.get("BUILD_ID") or None
