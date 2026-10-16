"""A planned stop of the service process is clean (archiver#297).

``systemctl stop`` sends SIGTERM. The unit runs the venv's uvicorn directly, which
shuts the app down and then re-raises the signal, so the process dies *by*
SIGTERM: ``-15`` here, and clean to systemd for any type but oneshot. The stop
ends ``inactive``, so ``Restart=on-failure`` does nothing and a ``StartLimit*``
burst is never spent on a deploy. Under ``uv run`` it was exit **code** 143 and
ended ``failed`` (the 2026-09-30 deploy of #296), which is why the issue was filed.

0 is accepted too: a uvicorn that stops re-raising still stops cleanly. Anything
else means a planned stop counts as a failure, which is what this pins against.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_healthy(port: int, process: subprocess.Popen, deadline_s: float = 30.0) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        assert process.poll() is None, "uvicorn exited before serving"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"/health did not answer within {deadline_s} s")


def test_sigterm_ends_the_process_cleanly() -> None:
    port = _free_port()
    # The unit's command, from this venv, against the test database; no broker,
    # no monitor id, nothing a test may not hold (tests/conftest.py).
    env = {
        "PATH": os.environ.get("PATH", ""),
        "ARCHIVER_DATABASE_URL": os.environ["TEST_DATABASE_URL"],
    }
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
            "--log-config",
            "src/core/log_config.json",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_healthy(port, process)
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode in (0, -signal.SIGTERM), output
    assert "Application shutdown complete." in output
