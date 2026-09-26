"""needrestart lists restarts and never performs them (archiver#278).

apt's ``DPkg::Post-Invoke`` hook (``/etc/apt/apt.conf.d/99needrestart``) runs
``needrestart -m u`` after every dpkg run. Ubuntu's patch turns ``-m u`` into
**automatic** restarts when ``$nrconf{restart}`` is unset - the stock state -
so a ``libc6`` security update would restart ``postgresql@16-main`` and
``archiver.service`` mid-apply, outside any approval. ``NEEDRESTART_MODE=l``
in the environment overrides that only if it survives every process between
the operator and the hook; this drop-in makes the answer not depend on it.
Same shape as CannObserv/broker ``ad03a3d`` (broker#65).

Tracked in ``deploy/``, installed as:

- ``needrestart.conf.d/archiver.conf`` -> ``/etc/needrestart/conf.d/``

Pure assertions on the tracked copy run everywhere. Installed parity and the
live config chain assert only on the archiver host, identified by its
installed ``archiver.service`` - so CI and dev clones skip, and this host
fails until the drop-in is installed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
DROPIN = DEPLOY / "needrestart.conf.d" / "archiver.conf"
INSTALLED = Path("/etc/needrestart/conf.d/archiver.conf")
MAIN_CONF = Path("/etc/needrestart/needrestart.conf")
ARCHIVER_UNIT = Path("/etc/systemd/system/archiver.service")

# needrestart's config is Perl, eval'd into `%nrconf`. Evaluating it the same
# way is the only honest parse: a syntax error makes needrestart die, and the
# apt hook swallows that with `|| true`.
_EVAL = (
    "our %nrconf; our $LOGPREF = q(); "
    "eval do { local(@ARGV, $/) = $ARGV[0]; <> }; die $@ if $@; "
    "print defined $nrconf{restart} ? $nrconf{restart} : q(undef);"
)


def _restart_mode(conf: Path) -> str:
    """Return ``$nrconf{restart}`` after evaluating ``conf`` as needrestart does."""
    perl = shutil.which("perl")
    if perl is None:
        pytest.skip("perl not available on this host")
    return subprocess.run(
        [perl, "-e", _EVAL, str(conf)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _require_archiver_host() -> None:
    """Skip unless this host runs archiver.service."""
    if not ARCHIVER_UNIT.exists():
        pytest.skip(f"{ARCHIVER_UNIT} not present - not the archiver host")


def test_dropin_sets_list_only_restart_mode() -> None:
    assert _restart_mode(DROPIN) == "l"


def test_dropin_sets_nothing_else() -> None:
    """One key, so the drop-in cannot quietly change needrestart's other
    behaviour, and ``$nrconf{ui}`` stays unset - setting it would force
    interactive mode instead."""
    lines = [
        ln.strip()
        for ln in DROPIN.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert lines == ["$nrconf{restart} = 'l';"]


def test_installed_copy_matches_tracked() -> None:
    _require_archiver_host()
    assert INSTALLED.exists(), (
        f"{INSTALLED} is missing on the archiver host.\n"
        f"Install with:\n  sudo install -m 644 {DROPIN} {INSTALLED}"
    )
    assert INSTALLED.read_text() == DROPIN.read_text()


def test_live_config_chain_resolves_to_list_only() -> None:
    """The main config evals ``conf.d/*.conf`` in sort order, so a later file
    could override this one. Evaluate the chain needrestart itself reads."""
    _require_archiver_host()
    if not MAIN_CONF.exists():
        pytest.skip("needrestart not installed on this host")
    assert _restart_mode(MAIN_CONF) == "l"
