"""The installed Redis drop-in must match the repo copy, and must set a cap.

archiver#128. ``deploy/redis-server.dropin.conf`` was installed to
``/etc/systemd/system/redis-server.service.d/archiver.conf`` by hand and nothing
verified it stayed in sync — the same drift class
``test_installed_unit_matches_repo`` exists to catch for ``archiver.service``,
but for the broker Archiver operates rather than the service it runs.

The drift here is sharper than a stale flag. ``maxmemory-policy noeviction``
without an explicit ``maxmemory`` is *inert*: with the default ``maxmemory 0``
there is no ceiling to refuse writes at, so the bounded "error and let the outbox
retry" degradation the drop-in documents never engages and an untrimmed stream
grows until the kernel OOM-kills ``redis-server``. A drop-in that says
``noeviction`` while the broker runs uncapped reads as protection and provides
none.

Two assertions, deliberately split:

- The repo file declares a non-zero cap — pure, runs in CI, locks the invariant.
- The installed file matches the repo — skips when absent, so CI and dev clones
  pass; it asserts only on a host that actually runs the broker.
"""

import re
from pathlib import Path

import pytest

REPO_DROPIN = Path(__file__).resolve().parents[2] / "deploy" / "redis-server.dropin.conf"
INSTALLED_DROPIN = Path("/etc/systemd/system/redis-server.service.d/archiver.conf")

# `--maxmemory 0` disables the cap, which is the exact failure this guards.
_MAXMEMORY_ARG = re.compile(r"--maxmemory\s+(?!0\b)(\S+)")


def _read_if_installed(path: Path) -> str | None:
    """Return the drop-in's text, or None when it is genuinely not installed.

    Only ``FileNotFoundError`` means "not installed" — a ``PermissionError``
    propagates rather than becoming a silent pass, matching
    ``test_installed_unit_matches_repo``.
    """
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def test_repo_dropin_sets_an_explicit_nonzero_maxmemory() -> None:
    """`noeviction` is only meaningful with a ceiling to refuse writes at.

    Paired with ``OutOfMemoryError`` being transient in
    ``src/core/changes/publisher.py``: the cap turns memory pressure into a
    retryable ``OOM command not allowed`` instead of a broker kill, and the
    classification keeps that from dead-lettering valid events. Neither half
    stands alone.
    """
    text = REPO_DROPIN.read_text()
    assert "--maxmemory-policy noeviction" in text
    assert _MAXMEMORY_ARG.search(text), (
        "deploy/redis-server.dropin.conf must set an explicit non-zero "
        "--maxmemory; noeviction without a cap never refuses a write, so the "
        "broker is OOM-killed instead of erroring (archiver#128)."
    )


def test_installed_dropin_matches_repo() -> None:
    installed = _read_if_installed(INSTALLED_DROPIN)
    if installed is None:
        pytest.skip(f"{INSTALLED_DROPIN} not present — not a host running the broker")
    assert installed == REPO_DROPIN.read_text(), (
        f"{INSTALLED_DROPIN} has drifted from {REPO_DROPIN}.\n"
        "Reinstall with:\n"
        f"  sudo cp {REPO_DROPIN} {INSTALLED_DROPIN}\n"
        "  sudo systemctl daemon-reload && sudo systemctl restart redis-server\n"
        "Verify: redis-cli CONFIG GET maxmemory  # must not be 0"
    )
