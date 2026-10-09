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
from pathlib import Path

#: The release (or checkout) root: the project is installed editable, so this
#: module sits at ``<root>/src/core/``. ``resolve()`` follows ``live`` to the
#: physical release, so a later swap never changes what a process reports.
ROOT = Path(__file__).resolve().parents[2]


def build_id(root: Path | None = None) -> str | None:
    """The release's ``REVISION``, else the unit's ``BUILD_ID``, else None."""
    try:
        revision = ((root or ROOT) / "REVISION").read_text().strip()
    except FileNotFoundError:
        revision = ""
    return revision or os.environ.get("BUILD_ID") or None
