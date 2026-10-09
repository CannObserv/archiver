"""What ``/etc/systemd/system`` should hold: the live release's ``deploy/`` (archiver#330 D12).

``scripts/deploy.sh`` installs each unit from the release it switches to, so a
merged unit edit is not drift until it is deployed, and a difference from the
live release's copy is a hand edit. Before the cutover there is no ``live``
link and the installed units still run the checkout: nothing to compare.
"""

from pathlib import Path

import pytest

UNIT_DIR = Path("/etc/systemd/system")
LIVE = Path("/srv/archiver/live")


def installed_and_expected(
    name: str, *, unit_dir: Path = UNIT_DIR, live: Path = LIVE
) -> tuple[str, str]:
    """The installed unit's text and the live release's copy; skips where neither applies.

    Only ``FileNotFoundError`` means "not installed": a ``PermissionError``
    propagates, because a drift check that cannot fail reads as coverage while
    asserting nothing.
    """
    try:
        installed = (unit_dir / name).read_text()
    except FileNotFoundError:
        pytest.skip(f"{unit_dir / name} not installed - not a host running it")
    if not live.is_symlink():
        pytest.skip(f"{live} absent: not cut over yet; scripts/deploy.sh installs units from it")
    return installed, (live / "deploy" / name).read_text()


def drift_message(name: str, *, unit_dir: Path = UNIT_DIR, live: Path = LIVE) -> str:
    """How to read and fix a difference from the live release's copy."""
    return (
        f"{unit_dir / name} differs from the live release's copy ({live / 'deploy' / name}): "
        "a hand edit. Put it in deploy/, merge, and run scripts/deploy.sh, which installs it."
    )
