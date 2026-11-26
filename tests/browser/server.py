"""A real uvicorn on a loopback port for the browser tier (archiver#546).

A browser needs a socket, so this is the one place a test starts the app out of
process. It runs the checkout under test (``cwd`` is this tree's root, so a
``git archive`` of an older commit serves its own ``src/``), against the database
``tests/conftest.py`` pinned into ``ARCHIVER_DATABASE_URL`` and with the
environment that conftest scrubbed. No Playwright here: the kill-path test
imports this module in a bare child process.

Three guards, each for a way a server could outlive or overreach its run:

- **The database.** Refused unless its name ends in ``_test``; the app's own
  ``db_safety`` guard runs again inside the server.
- **The port.** Kernel-assigned on 127.0.0.1, and never 8000 (systemd's) or 8001
  (the dev server's), so it collides with neither.
- **The process.** ``stop()`` is terminate, then kill; and ``PR_SET_PDEATHSIG``
  kills the server if the pytest process dies without running teardown at all.
"""

import ctypes
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import httpx

from src.core.db_safety import database_name

ROOT = Path(__file__).resolve().parents[2]

#: systemd's live service and the dev server.
RESERVED_PORTS = frozenset({8000, 8001})
READY_TIMEOUT_SECONDS = 30.0
STOP_TIMEOUT_SECONDS = 10.0
_PR_SET_PDEATHSIG = 1
#: Resolved here, in the parent: between fork and exec the child runs only this
#: C call, never a library load, which could block on a lock another thread of
#: the parent held at the fork.
_prctl = ctypes.CDLL(None, use_errno=True).prctl


def free_port() -> int:
    """A kernel-assigned loopback port that is neither of the service ports.

    The socket closes before uvicorn binds, a small window another process could
    take the port in; uvicorn then fails to start, loudly, and readiness says so.
    """
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in RESERVED_PORTS:
            return port


def _die_with_parent(parent_pid: int):
    """A ``preexec_fn``: the child gets SIGKILL when the process that forked it dies."""

    def _arm() -> None:
        if _prctl(_PR_SET_PDEATHSIG, signal.SIGKILL) != 0:
            os._exit(70)
        # The parent may have died between fork and prctl: then nobody signals.
        if os.getppid() != parent_pid:
            os._exit(70)

    return _arm


def _server_env() -> dict[str, str]:
    """The pytest process's environment, as conftest pinned and scrubbed it.

    Less the GitHub PATs a ``.env`` load may have exported: the server needs
    none of them, as ``scripts/dev_server.sh`` reasons for ``GH_TOKEN``.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GH_TOKEN")}
    name = database_name(env.get("ARCHIVER_DATABASE_URL", "")) or ""
    if not name.endswith("_test"):
        raise RuntimeError(
            f"refusing to start the browser tier's server against {name or '<unset>'!r}:"
            " ARCHIVER_DATABASE_URL must name a _test database (tests/conftest.py pins it)"
        )
    return env


@dataclass
class LiveServer:
    """A started server: its process, port and log; ``stop()`` ends it."""

    process: subprocess.Popen
    port: int
    log: IO[str] = field(repr=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def log_tail(self, lines: int = 40) -> str:
        self.log.flush()
        self.log.seek(0)
        return "".join(self.log.readlines()[-lines:])

    def stop(self) -> None:
        """Terminate, then kill; safe to call twice."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(STOP_TIMEOUT_SECONDS)
        if not self.log.closed:
            self.log.close()


def start_server() -> LiveServer:
    """Start uvicorn on a free loopback port and wait until ``/health`` answers."""
    port = free_port()
    log = tempfile.TemporaryFile(mode="w+", prefix="browser-tier-uvicorn-")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=_server_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
        preexec_fn=_die_with_parent(os.getpid()),
    )
    server = LiveServer(process=process, port=port, log=log)
    try:
        _wait_ready(server)
    except BaseException:
        server.stop()
        raise
    return server


def _wait_ready(server: LiveServer) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            raise RuntimeError(
                f"uvicorn exited with {server.process.returncode}:\n{server.log_tail()}"
            )
        try:
            if httpx.get(f"{server.base_url}/health", timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"uvicorn not ready in {READY_TIMEOUT_SECONDS}s:\n{server.log_tail()}")
