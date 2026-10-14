"""The nightly backup's units (archiver#233): identity, sandbox, credentials, parity.

Ported from CannObserv/watcher's ``tests/deploy/test_backup_units.py``
(watcher#296, #297) and adapted to the release layout (archiver#330) and the
service-user rule (#339). The job runs as its own static system user,
``archiver_backup``, with no capabilities: ``pg_dump`` connects as that user,
by peer auth, to the ``pg_read_all_data`` role of the same name
(``scripts/setup-backup-role.sql``). Static, not ``DynamicUser=``:
``scripts/deploy.sh`` refuses a unit whose ``User=`` the host cannot resolve, and
a dynamic user resolves only while it runs. The keys arrive as systemd
credentials, which never enter a process environment.
"""

import stat
from pathlib import Path

import pytest

from src.core.backup import (
    BUCKET_ENV,
    GCS_CREDENTIAL,
    KEY_PATH_ENV,
    MONITOR_ID_ENV,
    RUN_DEADLINE_SECONDS,
)
from src.core.status_checkin import CREDENTIAL_NAME, MONITOR_ID_PATTERN
from src.core.status_checkin import TIMEOUT_SECONDS as CHECKIN_TIMEOUT_SECONDS
from tests.deploy.live_release import drift_message, installed_and_expected

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "deploy" / "archiver-backup.service"
TIMER = REPO / "deploy" / "archiver-backup.timer"
ROLE_SCRIPT = REPO / "scripts" / "setup-backup-role.sql"

RELEASE = "/srv/archiver/live"
USER = "archiver_backup"
GCS_KEY = "/etc/archiver/co-archiver-backup.json"
CHECKIN_KEY = "/etc/archiver/status-checkin.key"
#: co-archiver-backup, created disabled 2026-10-14 (CannObserv/status#41).
MONITOR_ID = "01M4XBGKAD52BN3J69B7AX95GS"


def _values(path: Path, directive: str) -> list[str]:
    prefix = f"{directive}="
    return [
        line.strip().removeprefix(prefix)
        for line in path.read_text().splitlines()
        if line.strip().startswith(prefix)
    ]


def _tokens(path: Path, directive: str) -> set[str]:
    return {token for value in _values(path, directive) for token in value.split()}


class TestIdentity:
    def test_runs_as_its_own_static_user_never_archiver_or_root(self) -> None:
        """Not ``archiver``: that is the owner role, with write and DDL rights a
        dump has no use for. Not ``exedev``: its #348 column allowlist withholds
        ``app_users.email`` and ``api_keys.key_hash``, so its dump would be
        silently incomplete."""
        assert _values(SERVICE, "User") == [USER]
        assert _values(SERVICE, "Group") == [USER]
        assert _values(SERVICE, "DynamicUser") == []

    def test_holds_no_capabilities_at_all(self) -> None:
        assert _values(SERVICE, "CapabilityBoundingSet") == [""]
        assert _values(SERVICE, "AmbientCapabilities") == []

    def test_the_database_role_is_the_unit_user(self) -> None:
        """Peer auth maps the OS user to the role of the same name, and there is
        no ident map on this cluster to translate between two."""
        assert f"\\set backup_role {USER}" in ROLE_SCRIPT.read_text()

    @pytest.mark.parametrize("name", ["ARCHIVER_ALLOW_PRODUCTION_DB", "ARCHIVER_BUS_CONSUMER"])
    def test_holds_no_production_opt_in(self, name: str) -> None:
        """``db_safety`` guards SQLAlchemy URLs; ``pg_dump`` by name never meets
        it. The opt-in stays with the units that need it, not a fourth."""
        assert not [v for v in _values(SERVICE, "Environment") if v.startswith(name)]


class TestSandbox:
    @pytest.mark.parametrize(
        "directive",
        [
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateTmp=yes",
            "NoNewPrivileges=yes",
            "LockPersonality=yes",
            "RestrictNamespaces=yes",
            "ProtectKernelTunables=yes",
            "ProtectKernelModules=yes",
            "ProtectControlGroups=yes",
        ],
    )
    def test_confined(self, directive: str) -> None:
        assert directive in SERVICE.read_text().splitlines()

    def test_reaches_only_the_socket_and_the_network(self) -> None:
        assert _tokens(SERVICE, "RestrictAddressFamilies") == {"AF_UNIX", "AF_INET", "AF_INET6"}

    def test_dumps_production_from_the_release_as_itself(self) -> None:
        """The release venv's python, not ``uv run``: uv wants a writable cache
        under ``$HOME``. No ``--run-as``: the job is already the database's user."""
        assert _values(SERVICE, "Type") == ["oneshot"]
        assert _values(SERVICE, "WorkingDirectory") == [RELEASE]
        assert _values(SERVICE, "ExecStart") == [
            f"{RELEASE}/.venv/bin/python -m src.core.backup --database archiver"
        ]

    def test_the_interpreter_is_visible_inside_the_sandbox(self) -> None:
        """``ProtectHome=yes`` hides /home: a venv python linked to a uv-managed
        interpreter under ``~/.local/share/uv`` would fail to exec (203/EXEC)."""
        interpreter = Path(_values(SERVICE, "ExecStart")[0].split()[0])
        if not interpreter.exists():
            pytest.skip(f"{interpreter} not present: not a host running the backup")
        assert not interpreter.resolve().is_relative_to("/home"), interpreter.resolve()

    def test_waits_for_the_server_and_the_tailnet(self) -> None:
        """Postgres, so a boot-time catch-up run does not race it; the tailnet,
        so the check-in reaches ``status``."""
        (after,) = _values(SERVICE, "After")
        assert {"postgresql.service", "tailscaled.service"} <= set(after.split())

    def test_a_wedged_run_is_a_failed_unit_within_the_night(self) -> None:
        (value,) = _values(SERVICE, "TimeoutStartSec")
        assert 600 <= int(value) <= 3600

    def test_the_run_deadline_leaves_room_for_the_alert(self) -> None:
        """Killed by systemd, a run sends nothing, and a hang reads as silence
        for up to 26 h. The job's own deadline fires first, so it alerts."""
        (value,) = _values(SERVICE, "TimeoutStartSec")
        assert RUN_DEADLINE_SECONDS + CHECKIN_TIMEOUT_SECONDS + 60 <= int(value)

    def test_has_no_retry_loop(self) -> None:
        """The next night is the retry; a failure is an ``alert`` check-in."""
        assert _values(SERVICE, "Restart") == []


class TestCredentials:
    def test_keys_arrive_as_credentials_not_environment(self) -> None:
        """systemd reads each root-only file and hands the run a private copy
        under ``$CREDENTIALS_DIRECTORY``. The GCS SDK takes a path, so it gets
        the copy's. The Status key is the tenant's one key, drift's too."""
        assert set(_values(SERVICE, "LoadCredential")) == {
            f"{GCS_CREDENTIAL}:{GCS_KEY}",
            f"{CREDENTIAL_NAME}:{CHECKIN_KEY}",
        }
        assert f"{KEY_PATH_ENV}=%d/{GCS_CREDENTIAL}" in _values(SERVICE, "Environment")

    def test_only_the_check_in_key_has_a_fallback(self) -> None:
        """No GCS key is a failed start (243/CREDENTIALS): there is nothing to
        ship to. No Status key is a backup that logs it cannot check in."""
        assert _values(SERVICE, "SetCredential") == [f"{CREDENTIAL_NAME}:\\n"]

    def test_reads_no_env_file(self) -> None:
        """``/etc/archiver/.env`` holds the database, Redis and Power Map
        secrets. And an env file setting ``GOOGLE_APPLICATION_CREDENTIALS``
        would beat the unit's ``%d/gcs``."""
        assert _values(SERVICE, "EnvironmentFile") == []

    def test_names_its_bucket(self) -> None:
        assert f"{BUCKET_ENV}=co-gcs-archiver-backup" in _values(SERVICE, "Environment")

    def test_names_the_monitor(self) -> None:
        """co-archiver-backup, tenant co-archiver (CannObserv/status#41)."""
        assert f"{MONITOR_ID_ENV}={MONITOR_ID}" in _values(SERVICE, "Environment")
        assert MONITOR_ID_PATTERN.fullmatch(MONITOR_ID)

    @pytest.mark.parametrize("key", [GCS_KEY, CHECKIN_KEY], ids=["gcs", "checkin-key"])
    def test_an_installed_key_is_readable_only_by_root(self, key: str) -> None:
        """Only systemd reads the file; the job reads its private copy. Mode by
        ``stat``, never the contents."""
        path = Path(key)
        if not path.exists():
            pytest.skip(f"{path} not installed: not a host running the backup")
        info = path.stat()
        assert info.st_uid == 0, f"{path} must be owned by root"
        assert not info.st_mode & (stat.S_IRWXG | stat.S_IRWXO), (
            f"{path} is mode {stat.S_IMODE(info.st_mode):o}; install it 0400 root:root"
        )


class TestTimer:
    def test_nightly_and_catches_up_after_downtime(self) -> None:
        """Watcher's slot and jitter. ``Persistent=true`` runs a night a reboot
        skipped."""
        assert _values(TIMER, "OnCalendar") == ["*-*-* 03:17:00 UTC"]
        assert _values(TIMER, "RandomizedDelaySec") == ["10min"]
        assert _values(TIMER, "Persistent") == ["true"]
        assert _values(TIMER, "Unit") == ["archiver-backup.service"]

    def test_is_enabled_by_hand_into_timers(self) -> None:
        """``deploy.sh`` installs it and prints the enable hint; never enables it."""
        assert _values(TIMER, "WantedBy") == ["timers.target"]


@pytest.mark.parametrize("name", ["archiver-backup.service", "archiver-backup.timer"])
def test_installed_unit_matches_the_live_release(name: str) -> None:
    """archiver#330 D12: what a host should hold is the live release's copy."""
    installed, expected = installed_and_expected(name)
    assert installed == expected, drift_message(name)
