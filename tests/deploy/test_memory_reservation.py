"""Drift tests for the production memory reservation (archiver#237).

This host is 3.8 GiB with no swap, and it runs the live service, PostgreSQL
and interactive agent sessions on one kernel. The failure this guards against
is not an OOM kill - it is the *absence* of one. Past the ceiling the kernel
fails atomic allocations in whatever asks next (``tailscaled``, ``ksoftirqd``)
and the production service is what goes down: CannObserv/broker lost its bus
for 57m 48s that way on 2026-09-16 (gregoryfoster/skills#295,
``references/troubleshooting.md`` row U).

Four settings, none a substitute for another:

* ``MemoryLow=`` - a soft floor reclaim will not take the working set below.
  Inert unless every slice above the unit grants it too (CannObserv/notifier#85).
* ``OOMScoreAdjust=`` - puts production behind everything killable. Sessions
  here read 0 (archiver#285), so that includes them; see the session premise at
  the foot.
* ``vm.min_free_kbytes`` - the reserve atomic allocations draw on. The other
  two are per-cgroup and cannot help an allocation in ``ksoftirqd``.
* earlyoom - kills a session before the kernel has to pick. Adopted once
  sessions read 0 (archiver#285); at -1000 it reached none of them.

Two premises belong to the host rather than the repo - what the kernel grants,
and what score exe.dev starts a session at - so those tests read the live host
and skip everywhere else, CI included.
"""

import math
import os
import re
import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"

PROD_UNIT = DEPLOY / "archiver.service"
BUS_HEALTH_UNIT = DEPLOY / "archiver-bus-health.service"
POSTGRES_UNIT = DEPLOY / "postgresql@16-main.service.d" / "10-memory.conf"
SYSCTL = DEPLOY / "99-archiver-memory.conf"
EARLYOOM = DEPLOY / "earlyoom.default"

#: Live peaks (``memory.peak``) on co-registrar, 2026-09-28: archiver.service
#: 193 MiB after ~30h up, postgresql@16-main 281 MiB after 2.7 days. A floor
#: must clear its unit's own peak, or it reserves less than the unit uses.
MEASURED_PROD_PEAK_MIB = 193
MEASURED_POSTGRES_PEAK_MIB = 281

MIB = 1024 * 1024

#: The host this repo deploys to. The live tests read its kernel.
HOST = "co-registrar"
live_host_only = pytest.mark.skipif(
    socket.gethostname() != HOST, reason=f"reads {HOST}'s live kernel state"
)

CGROUP_FS = Path("/sys/fs/cgroup")
PROC_FS = Path("/proc")


def directives(unit: Path) -> str:
    """The lines systemd acts on, comments and blanks dropped."""
    return "\n".join(
        line
        for line in unit.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def setting(unit: Path, key: str) -> str | None:
    """The value of a ``Key=value`` directive, or None when unset."""
    for line in directives(unit).splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def section_of(unit: Path, key: str) -> str | None:
    """The ``[Section]`` a ``Key=`` directive sits in, or None when unset."""
    section = None
    for line in directives(unit).splitlines():
        if line.startswith("["):
            section = line.strip("[] ")
        elif line.startswith(f"{key}="):
            return section
    return None


def _mib(value: str) -> int:
    """Parse a systemd memory value into whole MiB."""
    match = re.fullmatch(r"(\d+)([KMG]?)", value)
    assert match, f"unparseable memory value {value!r}"
    amount, suffix = int(match.group(1)), match.group(2)
    return {"": amount // MIB, "K": amount // 1024, "M": amount, "G": amount * 1024}[suffix]


def unit_of(path: Path) -> str:
    """The unit a deploy file configures: its own name, or its drop-in directory's."""
    parent = path.parent.name
    return parent.removesuffix(".d") if parent.endswith(".d") else path.name


def claiming_files() -> list[Path]:
    """The deploy files that set ``MemoryLow=``."""
    return [
        path
        for path in sorted(DEPLOY.rglob("*"))
        if path.is_file() and setting(path, "MemoryLow") is not None
    ]


def declared_lows() -> dict[str, int]:
    """Every ``MemoryLow=`` under ``deploy/``, in MiB, by unit."""
    lows: dict[str, int] = {}
    for path in claiming_files():
        unit = unit_of(path)
        assert unit not in lows, f"{unit} sets MemoryLow= in two deploy files"
        lows[unit] = _mib(setting(path, "MemoryLow"))
    return lows


def parent_slice(unit: str) -> str | None:
    """The slice systemd puts a system unit in by default; None above system.slice.

    A plain unit lands in ``system.slice``; a template instance ``foo@bar.service``
    in the implicit ``system-foo.slice``, which grants 0 like any other link.
    ``-`` is escaped to ``\\x2d`` there, since ``-`` separates slice levels.
    """
    name, _, kind = unit.rpartition(".")
    if kind == "slice":
        prefix = name.rpartition("-")[0]
        return f"{prefix}.slice" if prefix else None
    if "@" in name:
        template = name.split("@")[0].replace("-", "\\x2d")
        return f"system-{template}.slice"
    return "system.slice"


def cgroup_of(unit: str) -> str:
    """The cgroup path ``parent_slice`` places ``unit`` at, as ``ControlGroup=`` spells it."""
    chain = [unit]
    while (parent := parent_slice(chain[-1])) is not None:
        chain.append(parent)
    return "/" + "/".join(reversed(chain))


# -- the production units take the reservation --------------------------------


def test_production_unit_reserves_a_floor_above_its_peak():
    """MemoryLow=, clearing the measured working set."""
    value = setting(PROD_UNIT, "MemoryLow")
    assert value is not None, "archiver.service declares no MemoryLow= floor"
    assert _mib(value) > MEASURED_PROD_PEAK_MIB, (
        f"MemoryLow={value} is at or under the {MEASURED_PROD_PEAK_MIB} MiB this "
        "service peaked at, so it reserves less than the working set"
    )


def test_postgres_reserves_a_floor_above_its_peak():
    """The registry is only as protected as its database.

    The service's floor keeps its own pages resident; a request still stalls on
    a reclaimed page of the cluster behind it.
    """
    assert POSTGRES_UNIT.is_file(), f"{POSTGRES_UNIT.relative_to(DEPLOY)} is missing"
    value = setting(POSTGRES_UNIT, "MemoryLow")
    assert value is not None, "the PostgreSQL drop-in declares no MemoryLow= floor"
    assert _mib(value) > MEASURED_POSTGRES_PEAK_MIB, (
        f"MemoryLow={value} is at or under the {MEASURED_POSTGRES_PEAK_MIB} MiB "
        "PostgreSQL peaked at, so it reserves less than the working set"
    )


@pytest.mark.parametrize("unit", [PROD_UNIT, POSTGRES_UNIT], ids=["archiver", "postgres"])
@pytest.mark.parametrize("key", ["MemoryMax", "MemoryHigh"])
def test_production_units_are_never_capped(unit, key):
    """A cap bounds the victim, not the cause.

    ``MemoryHigh=`` throttles reclaim rather than failing an allocation, so the
    unit crawls while still reporting ``active``. The cap belongs on the
    SocratiCode pre-install, a deliberate one-off, never the always-on service.
    """
    assert setting(unit, key) is None, f"{unit.name} sets {key}="


def test_production_unit_is_deprioritised_for_the_killer():
    """Negative, but never -1000.

    -1000 makes the unit unkillable, so a leak in it wedges a swapless host
    rather than shedding one process. Postgres needs no line here: Debian's
    ``postgresql@.service`` already ships -900.
    """
    value = setting(PROD_UNIT, "OOMScoreAdjust")
    assert value is not None, "archiver.service declares no OOMScoreAdjust="
    assert -1000 < int(value) < 0, f"OOMScoreAdjust={value} must be in (-1000, 0)"


def test_the_bus_health_probe_takes_no_reservation():
    """A oneshot WARN tick; a reservation everything holds is one nobody holds."""
    for key in ("MemoryLow", "OOMScoreAdjust"):
        assert setting(BUS_HEALTH_UNIT, key) is None, f"archiver-bus-health sets {key}="


# -- every slice above a floor grants it ---------------------------------------


def test_every_slice_above_a_floor_grants_exactly_what_its_children_claim():
    """cgroup v2 caps a unit's protection at what every ancestor grants.

    ``system.slice`` ships ``memory.low`` 0, so a unit's own ``MemoryLow=`` alone
    protects nothing while ``systemctl show`` reports it set (notifier#85). The
    templated postgres instance adds a link, ``system-postgresql.slice``.
    Exactly the sum: less and each child keeps a usage-proportional share; more
    is protection nothing here claims.
    """
    lows = declared_lows()
    children: dict[str, set[str]] = {}
    for unit in lows:
        child = unit
        while (parent := parent_slice(child)) is not None:
            children.setdefault(parent, set()).add(child)
            child = parent
    assert "system.slice" in children, "no floor under deploy/ to grant - the test is vacuous"
    for slice_, members in sorted(children.items()):
        claimed = sum(lows.get(member, 0) for member in members)
        assert slice_ in lows, (
            f"{slice_} grants nothing, so {sorted(members)} keep no protection: "
            f"add deploy/{slice_}.d/10-memory-protection.conf"
        )
        assert lows[slice_] == claimed, (
            f"{slice_} grants MemoryLow={lows[slice_]}M but {sorted(members)} "
            f"claim {claimed}M; grant exactly the sum"
        )


def test_every_floor_sits_in_the_section_its_unit_type_reads():
    """``[Slice]`` in a slice drop-in, ``[Service]`` in a service's.

    systemd skips a section its unit type does not read with one journal line:
    the drop-in loads, ``daemon-reload`` succeeds, and the floor is inert.
    """
    expected = {"service": "Service", "slice": "Slice"}
    for path in claiming_files():
        kind = unit_of(path).rpartition(".")[2]
        assert section_of(path, "MemoryLow") == expected[kind], (
            f"{path.relative_to(DEPLOY)} sets MemoryLow= outside [{expected[kind]}]"
        )


def _memory_low(cgroup: Path) -> float:
    """A cgroup's ``memory.low`` in bytes; ``max`` is unbounded."""
    value = (cgroup / "memory.low").read_text().strip()
    return math.inf if value == "max" else int(value)


def weakest_link(fs: Path, cgroup: str) -> tuple[str, float]:
    """The lowest ``memory.low`` from ``cgroup`` up, and the cgroup that sets it.

    Without ``memory_recursiveprot`` (this host's mount) the unit keeps at most
    this: the kernel scales a child's protection by its parent's effective
    protection (``effective_protection()`` in ``mm/page_counter.c``).
    """
    links = []
    while cgroup not in ("", "/"):
        links.append((cgroup, _memory_low(fs / cgroup.lstrip("/"))))
        cgroup = cgroup.rpartition("/")[0]
    return min(links, key=lambda link: link[1])


def oversubscribed(fs: Path, cgroup: str) -> list[tuple[str, float, float]]:
    """``(slice, grant, claimed)`` for each slice above ``cgroup`` its children overdraw."""
    found = []
    cgroup = cgroup.rpartition("/")[0]
    while cgroup not in ("", "/"):
        node = fs / cgroup.lstrip("/")
        claimed = sum(
            _memory_low(child) for child in node.iterdir() if (child / "memory.low").is_file()
        )
        if claimed > _memory_low(node):
            found.append((cgroup, _memory_low(node), claimed))
        cgroup = cgroup.rpartition("/")[0]
    return found


def _fake_cgroup(fs: Path, cgroup: str, low_mib: int) -> None:
    node = fs / cgroup.lstrip("/")
    node.mkdir(parents=True, exist_ok=True)
    (node / "memory.low").write_text(f"{low_mib * MIB}\n")


def test_a_template_instance_lands_in_its_implicit_slice():
    assert cgroup_of("postgresql@16-main.service") == (
        "/system.slice/system-postgresql.slice/postgresql@16-main.service"
    )
    assert parent_slice("serial-getty@ttyS0.service") == "system-serial\\x2dgetty.slice"


def test_a_slice_at_zero_clamps_the_unit_below_it(tmp_path):
    """This host as found on 2026-09-28: system.slice at 0."""
    _fake_cgroup(tmp_path, "/system.slice", 0)
    _fake_cgroup(tmp_path, "/system.slice/archiver.service", 256)
    assert weakest_link(tmp_path, "/system.slice/archiver.service") == ("/system.slice", 0)


def test_children_claiming_past_the_grant_are_oversubscribed(tmp_path):
    _fake_cgroup(tmp_path, "/system.slice", 256)
    _fake_cgroup(tmp_path, "/system.slice/archiver.service", 256)
    _fake_cgroup(tmp_path, "/system.slice/system-postgresql.slice", 320)
    assert oversubscribed(tmp_path, "/system.slice/archiver.service") == [
        ("/system.slice", 256 * MIB, 576 * MIB)
    ]


@live_host_only
@pytest.mark.parametrize("unit", sorted(u for u in declared_lows() if u.endswith(".service")))
def test_the_live_floor_takes_effect(unit):
    """The effective protection is the only evidence.

    ``systemctl show -p MemoryLow``, the unit's own ``memory.low`` and a clean
    ``daemon-reload`` all agreed on wslcb-licensing-tracker while the floor
    protected nothing (gregoryfoster/skills#303).
    """
    cgroup = subprocess.run(
        ["systemctl", "show", unit, "-p", "ControlGroup", "--value"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not cgroup:
        pytest.skip(f"{unit} is not running")
    assert cgroup == cgroup_of(unit), f"{unit} runs in {cgroup}, not {cgroup_of(unit)}"
    link, low = weakest_link(CGROUP_FS, cgroup)
    claimed = declared_lows()[unit]
    assert low >= claimed * MIB, (
        f"{unit} claims {claimed} MiB but keeps at most {low / MIB:.0f}: {link} grants "
        "no more. Install deploy/'s drop-ins and daemon-reload (deploy/README.md)"
    )
    assert oversubscribed(CGROUP_FS, cgroup) == [], (
        "a slice above this unit grants less than its children claim"
    )


@live_host_only
def test_the_live_service_carries_its_oom_score():
    """``OOMScoreAdjust=`` applies at start: an unrestarted service still reads 0."""
    pid = subprocess.run(
        ["systemctl", "show", "archiver.service", "-p", "MainPID", "--value"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if pid in ("", "0"):
        pytest.skip("archiver.service is not running")
    live = int((PROC_FS / pid / "oom_score_adj").read_text())
    assert live == int(setting(PROD_UNIT, "OOMScoreAdjust")), (
        f"archiver.service's MainPID reads oom_score_adj={live}: restart it"
    )


# -- the half a cgroup cannot do -----------------------------------------------


def _min_free_kbytes(text: str) -> int | None:
    match = re.search(r"^vm\.min_free_kbytes\s*=\s*(\d+)", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def test_sysctl_drop_in_raises_the_atomic_allocation_reserve():
    """The kernel default here is 7999 kB, far too thin to absorb a 1.2 G spike."""
    assert SYSCTL.is_file(), f"{SYSCTL.name} is missing from deploy/"
    value = _min_free_kbytes(SYSCTL.read_text())
    assert value is not None, "the drop-in does not set vm.min_free_kbytes"
    assert value >= 65536, "a reserve under 64 MiB leaves this no-swap host where it started"


@live_host_only
def test_the_live_kernel_holds_the_reserve():
    live = int((PROC_FS / "sys" / "vm" / "min_free_kbytes").read_text())
    assert live == _min_free_kbytes(SYSCTL.read_text()), (
        f"vm.min_free_kbytes is {live} live: install {SYSCTL.name} to /etc/sysctl.d/ "
        "and run `sudo sysctl --system`"
    )


# -- the session premise: what a killer can take ------------------------------

#: What a session's root can hang from: PID 1 once the VS Code server has
#: daemonised, or exe.dev's own launchers.
SESSION_PARENTS = frozenset({"exe-init", "sshd"})


def session_root_adj(proc: Path, pid: int) -> int | None:
    """``oom_score_adj`` of the topmost ancestor of ``pid`` below PID 1 or a launcher.

    That root, not ``pid``: a leaf can be ``choom``'d, the root cannot. ``None``
    when the root is a systemd manager - a unit or a timer, not a session.
    """
    while pid > 1:
        status = (proc / str(pid) / "status").read_text()
        ppid = int(re.search(r"^PPid:\s*(\d+)", status, re.MULTILINE).group(1))
        parent_comm = (proc / str(ppid) / "comm").read_text().strip() if ppid > 1 else None
        if ppid <= 1 or parent_comm in SESSION_PARENTS:
            if (proc / str(pid) / "comm").read_text().strip() == "systemd":
                return None
            return int((proc / str(pid) / "oom_score_adj").read_text())
        pid = ppid
    return None


def _fake_process(proc: Path, pid: int, ppid: int, comm: str, adj: int) -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "status").write_text(f"Name:\t{comm}\nPPid:\t{ppid}\n")
    (proc / str(pid) / "comm").write_text(f"{comm}\n")
    (proc / str(pid) / "oom_score_adj").write_text(f"{adj}\n")


def test_a_daemonised_vscode_session_reports_its_root(tmp_path):
    """This host's shape, 2026-09-28: the VS Code server's ``sh`` under PID 1 at -1000."""
    _fake_process(tmp_path, 649, 1, "sh", -1000)
    _fake_process(tmp_path, 78254, 649, "claude", -1000)
    _fake_process(tmp_path, 900, 78254, "npm", 500)  # a choom'd leaf
    assert session_root_adj(tmp_path, 900) == -1000


def test_a_session_under_exe_init_reports_its_root_not_exe_init(tmp_path):
    """This host's shape after exe-init 14fd603 (archiver#285): only the launcher stays at -1000."""
    _fake_process(tmp_path, 215, 1, "exe-init", -1000)
    _fake_process(tmp_path, 559, 215, "bash", 0)
    _fake_process(tmp_path, 1080, 559, "claude", 0)
    assert session_root_adj(tmp_path, 1080) == 0


def test_a_session_under_sshd_reports_its_root(tmp_path):
    _fake_process(tmp_path, 218, 1, "sshd", -1000)
    _fake_process(tmp_path, 700, 218, "sshd-session", 0)
    _fake_process(tmp_path, 701, 700, "bash", 0)
    assert session_root_adj(tmp_path, 701) == 0


def test_a_unit_is_not_a_session(tmp_path):
    _fake_process(tmp_path, 300, 1, "systemd", 100)
    _fake_process(tmp_path, 301, 300, "python3", 0)
    assert session_root_adj(tmp_path, 301) is None


# -- earlyoom: adopted once sessions read 0 (archiver#285) ----------------------

#: What each regex must reach, as ``/proc/<pid>/comm`` spells it on this host.
#: ``npm exec socrat`` is the SocratiCode server, truncated to 15 characters.
PREFERRED_COMMS = ("MainThread", "claude", "npm exec socrat", "node", "npx")
AVOIDED_COMMS = ("uv", "uvicorn", "postgres", "tailscaled", "systemd-journal", "sshd")
#: Session processes a ``$``-anchor or a truncation must not make it miss.
NOT_AVOIDED_COMMS = ("MainThread", "claude", "npm exec socrat", "code-04c0d99f4f")


def earlyoom_value() -> str:
    """The ``EARLYOOM_ARGS`` value, its surrounding double quotes stripped."""
    for line in EARLYOOM.read_text().splitlines():
        if line.startswith("EARLYOOM_ARGS="):
            value = line.split("=", 1)[1].strip()
            assert value.startswith('"') and value.endswith('"'), line
            return value[1:-1]
    raise AssertionError(f"{EARLYOOM.name} sets no EARLYOOM_ARGS=")


def earlyoom_args() -> list[str]:
    """What systemd hands earlyoom: Debian's unit expands ``$EARLYOOM_ARGS`` unquoted.

    By then the file's quotes are gone, so the value splits on every blank.
    """
    return earlyoom_value().split()


def earlyoom_option(flag: str) -> str:
    args = earlyoom_args()
    assert args.count(flag) == 1, f"{flag} must appear exactly once: {args}"
    return args[args.index(flag) + 1]


def test_an_earlyoom_config_ships():
    assert EARLYOOM.exists(), f"{EARLYOOM} is missing: earlyoom runs on stock arguments"


def test_earlyoom_regexes_survive_the_unquoted_split():
    """A blank splits a regex into two arguments; a backslash is dropped (skills#303)."""
    value = earlyoom_value()
    assert "\\" not in value, f"a backslash does not survive systemd's split: {value}"
    assert "'" not in value and '"' not in value, f"inner quotes do not survive: {value}"
    for flag in ("--prefer", "--avoid"):
        regex = earlyoom_option(flag)
        assert not regex.startswith("-"), f"{flag} lost its regex to the split: {regex}"
        re.compile(regex)


@pytest.mark.parametrize("comm", PREFERRED_COMMS)
def test_earlyoom_prefers_session_tooling(comm):
    """Start-anchored, never ``$``-anchored: comm is truncated to 15 chars (skills#307)."""
    assert re.search(earlyoom_option("--prefer"), comm), f"--prefer misses {comm!r}"


@pytest.mark.parametrize("comm", AVOIDED_COMMS)
def test_earlyoom_avoids_production(comm):
    assert re.search(earlyoom_option("--avoid"), comm), f"--avoid misses {comm!r}"


@pytest.mark.parametrize("comm", NOT_AVOIDED_COMMS)
def test_earlyoom_does_not_avoid_a_session(comm):
    assert not re.search(earlyoom_option("--avoid"), comm), f"--avoid shields {comm!r}"


def test_earlyoom_acts_on_memory_alone():
    """``-s 100,100``: the package default waits on swap. Inert without swap, and right."""
    assert earlyoom_option("-s") == "100,100"


@live_host_only
def test_installed_earlyoom_config_matches_repo():
    installed = Path("/etc/default/earlyoom")
    assert installed.exists(), "earlyoom is not configured: see deploy/README.md"
    assert installed.read_text() == EARLYOOM.read_text(), (
        f"{installed} has drifted: sudo install -m 644 {EARLYOOM} {installed} "
        "&& sudo systemctl restart earlyoom"
    )


@live_host_only
def test_earlyoom_runs_the_configuration_as_written():
    """Installing starts it on stock arguments, and enable --now reloads nothing."""

    def show(prop: str) -> str:
        return subprocess.run(
            ["systemctl", "show", "earlyoom", "-p", prop, "--value"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert show("ActiveState") == "active", "earlyoom.service is not running"
    assert show("UnitFileState") == "enabled", "earlyoom.service will not come back on boot"
    cmdline = (PROC_FS / show("MainPID") / "cmdline").read_bytes().split(b"\0")
    argv = [arg.decode() for arg in cmdline if arg]
    assert argv[1:] == earlyoom_args(), (
        f"earlyoom runs {argv[1:]}, not {EARLYOOM.name}: sudo systemctl restart earlyoom"
    )


@live_host_only
def test_sessions_here_sit_at_0():
    """``OOMScoreAdjust=-500`` putting production behind a session rests on this.

    exe.dev's, not this repo's: an ``exe-init`` build started sessions at -1000,
    where no killer can take one, until 14fd603 replaced it (archiver#285,
    2026-09-29). It has changed across one reboot before (CannObserv/notifier#88).
    If it reads -1000 again, check ``/exe.dev/bin/exe-init --version`` and
    reopen archiver#285.
    """
    adj = session_root_adj(PROC_FS, os.getpid())
    if adj is None:
        pytest.skip("not run from an interactive session")
    assert adj == 0, f"this session's root reads oom_score_adj={adj}, not 0"
