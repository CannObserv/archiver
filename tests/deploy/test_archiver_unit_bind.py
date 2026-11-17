"""``archiver.service`` binds loopback only (archiver#517).

The dashboard's identity is the exe.dev proxy's ``X-ExeDev-UserID`` and
``X-ExeDev-Email`` headers, trusted from any peer. The proxy connects from
``127.0.0.1`` (measured on 8001 in #404 and on 8000 in #517), so a loopback bind
keeps it and refuses every path that has no proxy in front of it: ``eth0`` and
``tailscale0``. ``docs/reference/tailscale.md`` D3 is the decision.
"""

import shlex
from pathlib import Path

REPO_UNIT = Path(__file__).resolve().parents[2] / "deploy" / "archiver.service"


def _exec_start_argv() -> list[str]:
    lines = [
        line.strip().partition("=")[2]
        for line in REPO_UNIT.read_text().splitlines()
        if line.strip().startswith("ExecStart=")
    ]
    assert len(lines) == 1, lines
    return shlex.split(lines[0])


def _option(argv: list[str], name: str) -> list[str]:
    """Every value given for ``name``, in either ``--name v`` or ``--name=v`` form."""
    values = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == name]
    return values + [arg.partition("=")[2] for arg in argv if arg.startswith(f"{name}=")]


def test_uvicorn_binds_loopback_on_8000() -> None:
    argv = _exec_start_argv()
    assert argv[0].endswith("/uvicorn")
    assert _option(argv, "--host") == ["127.0.0.1"]
    assert _option(argv, "--port") == ["8000"]


def test_no_socket_or_fd_bind_sidesteps_the_host() -> None:
    """``--uds`` and ``--fd`` replace ``--host``: either would void the pin above."""
    argv = _exec_start_argv()
    assert not _option(argv, "--uds")
    assert not _option(argv, "--fd")
