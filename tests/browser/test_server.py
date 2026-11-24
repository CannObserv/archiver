"""The browser tier's loopback server: where it binds, and that it always goes away.

A server left behind by a run holds ``archiver_test`` connections and a port. A
killed gate that leaves state behind poisons the next one (about 2,687 setup
errors until ``information`` is dropped), so stopping is tested on both paths:
the fixture's own teardown, and the parent dying without one (SIGKILL).
"""

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from tests.browser.server import ROOT, LiveServer, free_port, start_server

_RESERVED = (8000, 8001)


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie is dead for every purpose here; /proc says so.
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().split()[2] != "Z"


def _wait(predicate, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


async def _backend_pids(conn) -> set[int]:
    """Other backends on this database, read in a transaction of its own.

    ``pg_stat_activity`` is a per-transaction snapshot: two reads in one
    transaction see the same rows, so each read ends its transaction.
    """
    rows = await conn.execute(
        text(
            "SELECT pid FROM pg_stat_activity"
            " WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
    )
    pids = {r[0] for r in rows}
    await conn.rollback()
    return pids


def test_free_port_is_loopback_ephemeral_never_the_service_ports() -> None:
    for _ in range(20):
        port = free_port()
        assert port not in _RESERVED
        assert port > 1024


def test_the_session_server_is_up_on_loopback(live_server: LiveServer) -> None:
    assert live_server.base_url == f"http://127.0.0.1:{live_server.port}"
    assert live_server.port not in _RESERVED
    assert httpx.get(f"{live_server.base_url}/health", timeout=5).status_code == 200
    assert _pid_alive(live_server.process.pid)


async def test_stop_closes_the_port_and_releases_the_database(test_engine) -> None:
    """A second server, so the session's stays up for the other tests."""
    async with test_engine.connect() as conn:
        before = await _backend_pids(conn)
        server = start_server()
        try:
            # A dashboard page opens the server's pool; /health never touches it.
            r = httpx.get(
                f"{server.base_url}/dashboard/",
                headers={
                    "X-ExeDev-UserID": "browser-tier-stop",
                    "X-ExeDev-Email": "stop@example.test",
                },
                timeout=10,
            )
            assert r.status_code == 200
            opened = await _backend_pids(conn) - before
            assert opened, "the server opened no database connection to release"
        finally:
            server.stop()
            await conn.execute(
                text("DELETE FROM information.app_users WHERE external_id = 'browser-tier-stop'")
            )
            await conn.commit()

        assert not _pid_alive(server.process.pid)
        assert not _port_open(server.port)
        deadline = time.monotonic() + 10
        while (await _backend_pids(conn)) & opened and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert not (await _backend_pids(conn)) & opened


def test_stop_is_idempotent() -> None:
    server = start_server()
    server.stop()
    server.stop()
    assert not _pid_alive(server.process.pid)


def test_a_killed_parent_takes_the_server_with_it(tmp_path: Path) -> None:
    """SIGKILL runs no teardown; PR_SET_PDEATHSIG is what stops the server then."""
    report = tmp_path / "server.txt"
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "from tests.browser.server import start_server\n"
            "s = start_server()\n"
            "open(sys.argv[1], 'w').write(f'{s.process.pid} {s.port}')\n"
            "time.sleep(300)\n",
            str(report),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
    )
    try:
        assert _wait(lambda: report.exists() and report.read_text().strip(), 60), "no server"
        pid, port = map(int, report.read_text().split())
        assert _pid_alive(pid) and _port_open(port)
        child.send_signal(signal.SIGKILL)
        child.wait(10)
        assert _wait(lambda: not _pid_alive(pid)), f"server {pid} outlived its parent"
        assert _wait(lambda: not _port_open(port))
    finally:
        if child.poll() is None:
            child.kill()
        # CR 4: should PDEATHSIG fail, the server this test reports must not
        # outlive it, holding archiver_test connections into later runs.
        if report.exists() and report.read_text().strip():
            server_pid = int(report.read_text().split()[0])
            if _pid_alive(server_pid):
                os.kill(server_pid, signal.SIGKILL)
