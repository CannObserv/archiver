"""Drift tests for the production memory reservation (archiver#237).

This host is 7.7 GiB with a 4 G swapfile (archiver#286; 3.8 GiB and no swap
before), and it runs the live service, PostgreSQL and interactive agent sessions
on one kernel. The failure this guards against is not an OOM kill - it is the
*absence* of one. An atomic allocation cannot wait for swap, so past the reserve
the kernel fails one in whatever asks next (``tailscaled``, ``ksoftirqd``) and
the production service is what goes down: CannObserv/broker lost its bus for
57m 48s that way on 2026-09-16 (gregoryfoster/skills#295,
``references/troubleshooting.md`` row U).

Five settings, none a substitute for another:

* ``MemoryLow=`` - a soft floor reclaim will not take the working set below.
  Inert unless every slice above the unit grants it too (CannObserv/notifier#85).
* ``OOMScoreAdjust=`` - puts production behind everything killable. Sessions
  here read 0 (archiver#285), so that includes them; see the session premise at
  the foot.
* ``vm.min_free_kbytes`` - the reserve atomic allocations draw on. The other
  two are per-cgroup and cannot help an allocation in ``ksoftirqd``.
* The tail's order - ``OOMScoreAdjust=`` on ``tailscaled`` and
  ``PG_OOM_ADJUST_VALUE`` for postgres's children, which both sat at 0. With
  sessions at 0 the kernel takes a session first; these decide what goes after.
  earlyoom was measured and declined in their favour (archiver#285).
* Swap at ``vm.swappiness`` 10 - a slow path for reclaim, kept a last resort
  (archiver#286).

Four things belong to the host rather than the repo - what the kernel grants,
what score exe.dev starts a session at, what score the running tail processes
hold, and the swapfile - so those tests read the live host and skip everywhere
else, CI included.
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
TAILSCALED_DROPIN = DEPLOY / "tailscaled.service.d" / "10-oom.conf"
PG_ENVIRONMENT = DEPLOY / "postgresql" / "16" / "main" / "environment"
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

    -1000 makes the unit unkillable, so a leak in it wedges the host rather
    than shedding one process; swap only slows the leak down. The postmaster
    needs no line here: Debian's ``postgresql@.service`` already ships -900. Its
    children's score is ``PG_OOM_ADJUST_VALUE`` in the cluster's environment
    file (the tail, below).
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


def sysctl_value(text: str, key: str) -> int | None:
    """The integer ``key`` is set to in a sysctl drop-in, or None."""
    match = re.search(rf"^{re.escape(key)}\s*=\s*(\d+)", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def test_sysctl_drop_in_raises_the_atomic_allocation_reserve():
    """The kernel default is ~11 MB at 7.7 GiB, far too thin to absorb a 1.2 G spike.

    64 MiB is the cohort's absolute figure, not a share of RAM: replicator kept
    it at 7.75 GiB (CannObserv/replicator#99), and an atomic burst does not grow
    with the host.
    """
    assert SYSCTL.is_file(), f"{SYSCTL.name} is missing from deploy/"
    value = sysctl_value(SYSCTL.read_text(), "vm.min_free_kbytes")
    assert value is not None, "the drop-in does not set vm.min_free_kbytes"
    assert value >= 65536, "a reserve under 64 MiB is thinner than the cohort's figure"


@live_host_only
@pytest.mark.parametrize("key", ["vm.min_free_kbytes", "vm.swappiness"])
def test_the_live_kernel_holds_the_drop_in(key):
    live = int((PROC_FS / "sys" / key.replace(".", "/")).read_text())
    assert live == sysctl_value(SYSCTL.read_text(), key), (
        f"{key} is {live} live: install {SYSCTL.name} to /etc/sysctl.d/ "
        "and run `sudo sysctl --system`"
    )


# -- swap: the slow path (archiver#286) -----------------------------------------

#: The swapfile deploy/README.md creates, and its size. 4 G matches replicator
#: (CannObserv/replicator#99); the 30 GB disk is sized to hold it.
SWAPFILE = "/swapfile"
SWAP_GIB = 4


def test_sysctl_drop_in_keeps_swap_a_last_resort():
    """Swap is there so reclaim has somewhere to go, not to page the working set.

    Reclaim weighs anonymous pages against cache as ``swappiness : 200 -
    swappiness``: 60:140 at the kernel default, 10:190 here.
    """
    assert sysctl_value(SYSCTL.read_text(), "vm.swappiness") == 10


def capped_commands(doc: Path) -> list[str]:
    """Each ``systemd-run`` command in ``doc`` that sets ``MemoryMax=``, continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", doc.read_text())
    return [
        line.strip()
        for line in joined.splitlines()
        if "systemd-run" in line and "MemoryMax=" in line
    ]


def test_every_documented_cap_bounds_swap_too():
    """``MemoryMax=`` bounds RAM only; a scope's ``memory.swap.max`` defaults to max.

    With swap on the host, a job past its cap pages out and grinds instead of
    dying: 200 MB under ``MemoryMax=64M`` ran to completion here, and was killed
    (137) once ``MemorySwapMax=0`` was added (2026-09-29).
    """
    commands = capped_commands(REPO_ROOT / "docs" / "SOCRATICODE.md")
    assert commands, "docs/SOCRATICODE.md documents no capped command"
    unbounded = [c for c in commands if "MemorySwapMax=0" not in c]
    assert not unbounded, f"capped commands that can swap past their cap: {unbounded}"


@live_host_only
def test_the_swapfile_is_active():
    swaps = (PROC_FS / "swaps").read_text().splitlines()[1:]
    sizes = {line.split()[0]: int(line.split()[2]) for line in swaps}
    assert SWAPFILE in sizes, f"{SWAPFILE} is not swapped on: see deploy/README.md"
    assert sizes[SWAPFILE] * 1024 >= SWAP_GIB * 1024**3 - MIB, (
        f"{SWAPFILE} is {sizes[SWAPFILE]} KiB, not {SWAP_GIB} G"
    )


@live_host_only
def test_the_swapfile_survives_a_reboot():
    fstab = Path("/etc/fstab").read_text().splitlines()
    entries = [line.split() for line in fstab if line.strip() and not line.startswith("#")]
    assert any(e[0] == SWAPFILE and e[2] == "swap" for e in entries if len(e) >= 3), (
        f"/etc/fstab has no swap entry for {SWAPFILE}: it is off after the next reboot"
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


# -- earlyoom: measured and declined at 0 (archiver#285) -----------------------


def test_no_earlyoom_config_ships():
    """Declined on the 2026-09-29 measurement, not on #237's -1000 reading.

    With sessions at 0 the kernel, package-default earlyoom and the tuned config
    all named the same first victim, a session's ``MainThread``. earlyoom changed
    the timing: it killed at ~470 MiB available, page cache the kernel reclaims
    before it kills anything. What its ``--avoid`` added, a protected tail, is
    the ``OOMScoreAdjust=`` section below, which the kernel honours itself.
    """
    assert not EARLYOOM.exists(), f"{EARLYOOM.name} ships: earlyoom was declined (#285)"


@live_host_only
def test_earlyoom_is_not_running():
    state = subprocess.run(
        ["systemctl", "is-active", "earlyoom"], capture_output=True, text=True
    ).stdout.strip()
    assert state != "active", "earlyoom is running: sudo apt-get purge earlyoom (#285)"


# -- the tail: what the kernel takes after the sessions (archiver#285) ---------

#: Debian's ``postgresql@.service`` sets this on the postmaster. Its children
#: inherit it, then write ``PG_OOM_ADJUST_VALUE``; raising a score needs no
#: privilege, lowering one does, so no child can go below it.
POSTMASTER_OOM_SCORE_ADJ = -900


def environment(unit: Path) -> dict[str, str]:
    """Every ``Environment=`` assignment in a unit file."""
    pairs = [
        line.split("=", 1)[1]
        for line in directives(unit).splitlines()
        if line.startswith("Environment=")
    ]
    return dict(pair.split("=", 1) for pair in pairs)


def production_adj() -> int:
    return int(setting(PROD_UNIT, "OOMScoreAdjust"))


#: One postgresql.conf assignment: a bare value, or a single-quoted one that may
#: hold ``#``; then an optional trailing comment.
_CONF_LINE = re.compile(r"^\s*(\w+)\s*=\s*('(?:[^']|'')*'|[^\s#']*)\s*(?:#.*)?$")


def cluster_environment(path: Path) -> dict[str, str]:
    """``VARIABLE = value`` pairs, the postgresql.conf syntax pg_ctlcluster reads."""
    pairs = {}
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _CONF_LINE.match(line)
        assert match, f"{path.name}:{number} is not VARIABLE = value: {line!r}"
        key, value = match.groups()
        if value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        pairs[key] = value
    return pairs


def test_cluster_environment_parses_postgresql_conf_syntax(tmp_path):
    conf = tmp_path / "environment"
    conf.write_text("# header\nA = -500\nB = 'x # y'  # note\nC='it''s'\n")
    assert cluster_environment(conf) == {"A": "-500", "B": "x # y", "C": "it's"}


def test_cluster_environment_names_a_line_it_cannot_parse(tmp_path):
    conf = tmp_path / "environment"
    conf.write_text("A = 1\nnot an assignment\n")
    with pytest.raises(AssertionError, match="environment:2"):
        cluster_environment(conf)


def postgres_children_adj() -> int:
    value = cluster_environment(PG_ENVIRONMENT).get("PG_OOM_ADJUST_VALUE")
    assert value is not None, f"{PG_ENVIRONMENT.name} leaves postgres's children at 0"
    return int(value)


def test_the_postgres_unit_does_not_carry_the_childrens_score():
    """pg_ctlcluster starts the postmaster on an environment it builds itself.

    It keeps only the cluster's ``environment`` file (and LANG), so a systemd
    ``Environment=`` never reaches postgres: set there on 2026-09-29, the
    children still read 0 after a restart (archiver#285).
    """
    assert "PG_OOM_ADJUST_VALUE" not in environment(POSTGRES_UNIT), (
        f"{POSTGRES_UNIT.name} sets PG_OOM_ADJUST_VALUE, which pg_ctlcluster drops: "
        f"set it in {PG_ENVIRONMENT.relative_to(REPO_ROOT)}"
    )


def test_tailscaled_goes_after_sessions_and_before_production():
    """Below the sessions' 0, above archiver's -500, as on watcher (#309).

    It carries the bus and MagicDNS, but the API and dashboard are reached
    through the exe.dev proxy and the outbox buffers a bus outage, so archiver
    should outlive the tunnel.
    """
    adj = int(setting(TAILSCALED_DROPIN, "OOMScoreAdjust"))
    assert production_adj() < adj < 0, f"tailscaled's OOMScoreAdjust={adj}"


def test_postgres_children_rank_with_production():
    """Killing any child sends postgres into crash recovery: it is production too.

    Level with archiver.service, so under pressure from production the larger of
    the two goes, and never below the postmaster they inherit from.
    """
    adj = postgres_children_adj()
    assert adj == production_adj(), f"PG_OOM_ADJUST_VALUE={adj}, archiver is {production_adj()}"
    assert adj >= POSTMASTER_OOM_SCORE_ADJ, "a child cannot lower its inherited score"


@live_host_only
@pytest.mark.parametrize(
    ("repo", "installed"),
    [
        (TAILSCALED_DROPIN, "/etc/systemd/system/tailscaled.service.d/10-oom.conf"),
        (POSTGRES_UNIT, "/etc/systemd/system/postgresql@16-main.service.d/10-memory.conf"),
        (PG_ENVIRONMENT, "/etc/postgresql/16/main/environment"),
    ],
)
def test_the_tail_drop_ins_are_installed(repo, installed):
    path = Path(installed)
    assert path.exists() and path.read_text() == repo.read_text(), (
        f"install {repo.relative_to(REPO_ROOT)} to {path} (deploy/README.md)"
    )


def _main_pid(unit: str) -> str:
    return subprocess.run(
        ["systemctl", "show", unit, "-p", "MainPID", "--value"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@live_host_only
def test_the_live_tailscaled_carries_its_oom_score():
    """Applies at exec: an unrestarted tailscaled still reads 0."""
    pid = _main_pid("tailscaled.service")
    if pid in ("", "0"):
        pytest.skip("tailscaled is not running")
    live = int((PROC_FS / pid / "oom_score_adj").read_text())
    assert live == int(setting(TAILSCALED_DROPIN, "OOMScoreAdjust")), (
        f"tailscaled reads oom_score_adj={live}: restart it"
    )


@live_host_only
def test_the_live_postgres_children_carry_their_oom_score():
    """The postmaster reads its environment at start: a new value needs a restart."""
    pid = _main_pid("postgresql@16-main.service")
    if pid in ("", "0"):
        pytest.skip("postgresql@16-main is not running")
    children = (PROC_FS / pid / "task" / pid / "children").read_text().split()
    live = {}
    for child in children:
        # Backends come and go - the suite's own archiver_test connections among
        # them - so a child listed a moment ago may have exited.
        try:
            live[child] = int((PROC_FS / child / "oom_score_adj").read_text())
        except (FileNotFoundError, ProcessLookupError):
            continue
    assert live, "no postmaster child could be read"
    wrong = {child: adj for child, adj in live.items() if adj != postgres_children_adj()}
    assert not wrong, f"postgres children at {wrong}: restart postgresql@16-main"


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
