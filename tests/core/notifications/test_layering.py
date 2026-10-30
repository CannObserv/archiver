"""The renderer stays pure (Watcher #222 CR 2, archiver#367 D1).

``content``, ``diff`` and ``preview_fixtures`` render; they never load. Importing
them must not pull in the store side (the GCS SDK, a database session, the
Notifier SDK), which belongs to ``diff_loader``, ``item_facts`` and the adapter.
Checked in a fresh interpreter: this one has long since imported everything.

The ORM declarations are allowed: ``content_config`` (#363) takes the event
vocabulary from ``src.core.models.notification_subscription``, and declaring a
table does no I/O.
"""

import subprocess
import sys

import pytest

IO_MODULES = (
    "src.core.notifications.diff_loader",
    "src.core.notifications.item_facts",
    "google.cloud.storage",
    "sqlalchemy.ext.asyncio",
    "src.core.database",
    "notifier_client",
)


@pytest.mark.parametrize(
    "module",
    [
        "src.core.notifications.content",
        "src.core.notifications.diff",
        "src.core.notifications.preview_fixtures",
    ],
)
def test_rendering_modules_import_no_store_side(module: str) -> None:
    code = f"import sys, {module}; print(','.join(m for m in {IO_MODULES!r} if m in sys.modules))"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "", f"{module} loads the store side: {out}"
