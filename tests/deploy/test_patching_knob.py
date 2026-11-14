"""The patching-hosts knob reads clean, and keeps the decisions it records (#375).

``.skills/patching-hosts`` tells the vendored ``patching-hosts`` skill what only
this repo's owner knows: the window, the backup that stands in for a dump, the
command that says whether a job is running. **A malformed line makes the host
report-only** until it is fixed, which reads as "nothing to do" at the next run
rather than as an error, so the skill's own reader is run here.

The reader ships in the submodule. Off the host, a missing one is a skip; on
the host it's a failure. The rest are pure parses of the tracked files, run
everywhere, plus the installed GC timer and apt pins on the host:

- **The window is Mon 06:00-08:00 UTC, weekly**: the owner's Sun 22:00-24:00
  Pacific while PST holds (decided 2026-11-13, #375), clear of the backup's
  and the disk GC's timers, each under a quiet line.
- **No knob command escalates, or reads production's secrets**: ``inflight``,
  ``health`` and ``recovery`` run as the invoking user. A ``sudo`` hands root
  to the knob's committers, and ``/etc/archiver/.env`` is units-only (#339).
- **``inflight`` counts the oneshots by unit state**, with no database: every
  timer's service in ``deploy/`` has to match its glob, or a new timer could
  run through a step unseen.
- **``health`` is the DB-free ``/health`` on loopback**: an authenticated GET
  on 8000 upserts ``AppUser`` on production, and every probe runs ``health``.
- **The backup stands in for ``archiver`` alone.** ``archiver-backup.service``
  dumps one database, so the cluster's other two are exceptions, not declared
  databases.
- **Each timer's service is a non-restarter**: the probe can't follow
  ``python -m``, so each is an exception, pinned here to the unit facts that
  make it true.
- **Each followed origin is scoped by a tracked pin file**, catch-all below
  500 and its packages above (the skill's ``policy.md``, Two lanes).
- **A prune stage's soak ending stays green**: its review-by date is the
  probe's prompt for the next stage, not a deadline for every change's CI.
  Every other expired exception is red.
- **No ``image-owner``, and no private ``caller``**: this repo is public
  (gregoryfoster/skills#350).
"""

import json
import math
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOB = REPO_ROOT / ".skills" / "patching-hosts"
DEPLOY = REPO_ROOT / "deploy"
READ_KNOB = REPO_ROOT / "skills" / "patching-hosts" / "scripts" / "read-knob.sh"
INSTALLED_UNIT = Path("/etc/systemd/system/archiver.service")
#: The cohort disk GC's timer, installed from its layer, never from deploy/ (#440).
GC_TIMER = Path("/usr/local/lib/systemd/system/cannobserv-disk-gc.timer")
GC_TIMER_DROPIN = Path("/etc/systemd/system/cannobserv-disk-gc.timer.d")
PINS = DEPLOY / "apt-preferences.d"
INSTALLED_PINS = Path("/etc/apt/preferences.d")
HOST = "co-registrar"
#: Prune stages whose review-by date is a soak, not a deadline (pruning.md).
PRUNE_STAGES = ("disabled:", "removed:")
WINDOW = ["Mon", "06:00-08:00"]

#: Each followed origin's pin file, and the packages it was added for.
FOLLOWED = {
    "deb.nodesource.com": ("nodesource.pref", {"nodejs"}),
    "pkgs.tailscale.com": ("tailscale.pref", {"tailscale", "tailscale-archive-keyring"}),
}

#: Every Exec directive besides ExecStart= that a service unit can carry.
_OTHER_EXEC = (
    "ExecCondition",
    "ExecStartPre",
    "ExecStartPost",
    "ExecReload",
    "ExecStop",
    "ExecStopPost",
)


def _on_host() -> bool:
    return INSTALLED_UNIT.exists()


def _strip_comment(raw: str) -> str:
    """The directive part of a line: ``#`` opens a comment at a line's start or
    after whitespace (the skill's knob.md), so a command keeps a bare ``#``."""
    words = []
    for word in raw.split():
        if word.startswith("#"):
            break
        words.append(word)
    return " ".join(words)


def _named(directive: str) -> list[list[str]]:
    lines = (_strip_comment(raw).split() for raw in KNOB.read_text().splitlines())
    return [words[1:] for words in lines if words and words[0] == directive]


def _commands(directive: str) -> list[str]:
    return [" ".join(words) for words in _named(directive)]


def _values(text: str, directive: str) -> list[str]:
    prefix = f"{directive}="
    return [
        line.strip().removeprefix(prefix)
        for line in text.splitlines()
        if line.strip().startswith(prefix)
    ]


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _span_minutes(value: str) -> float:
    """A timer's one-unit span (``10min``, ``1800``, ``1h``) in minutes."""
    match = re.fullmatch(r"(\d+)\s*(s|sec|min|m|h)?", value.strip())
    assert match, f"unsupported span {value!r}"
    scale = {None: 1 / 60, "s": 1 / 60, "sec": 1 / 60, "min": 1, "m": 1, "h": 60}
    return int(match.group(1)) * scale[match.group(2)]


def _timer_span(path: Path) -> tuple[int, int]:
    """A daily timer's first and last start minute past midnight UTC.

    An unset ``AccuracySec=`` is systemd's default, one minute: the GC's timer
    sets none, so its starts run a minute past its randomized delay.
    """
    text = path.read_text()
    (calendar,) = _values(text, "OnCalendar")
    match = re.fullmatch(r"\*-\*-\* (\d\d:\d\d):00(?: UTC)?", calendar)
    assert match, f"{path.name}: unexpected OnCalendar={calendar}"
    start = _minutes(match.group(1))
    slack = sum(_span_minutes(v) for v in _values(text, "RandomizedDelaySec"))
    slack += sum(_span_minutes(v) for v in _values(text, "AccuracySec") or ["1min"])
    return start, start + math.ceil(slack)


def _pins(path: Path) -> list[dict[str, str]]:
    stanzas = []
    for block in re.split(r"\n\s*\n", path.read_text()):
        fields = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if line.strip() and not line.startswith("#")
        )
        if fields:
            stanzas.append(fields)
    return stanzas


def _timer_services() -> list[str]:
    return sorted(f"{timer.stem}.service" for timer in DEPLOY.glob("*.timer"))


def _read_knob(*extra: str) -> dict:
    if not READ_KNOB.is_file():
        if _on_host():
            pytest.fail(f"{READ_KNOB} missing on the host: git submodule update --init")
        pytest.skip("patching-hosts submodule not initialised")
    out = subprocess.run(
        ["bash", str(READ_KNOB), "--config", str(KNOB), "--host", HOST, *extra],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def _assert_clean(knob: dict) -> None:
    """Clean but for a prune stage's soak ending, which the probe reports."""
    soaking = {e["line"] for e in knob["exception"] if e["what"].startswith(PRUNE_STAGES)}
    assert [
        f
        for f in knob["findings"]
        if not (f["kind"] == "expired-exception" and f["line"] in soaking)
    ] == []
    assert knob["report_only"] is False, knob["report_only_reasons"]
    assert knob["class"]["value"] == "production"
    assert knob["posture"]["value"] == "scheduled"
    assert knob["cadence"]["value"] == "weekly"
    assert [(w["weekday"], w["week"], w["start"], w["end"]) for w in knob["window"]] == [
        ("Mon", None, "06:00", "08:00")
    ]
    assert not any(
        e["expired"] for e in knob["exception"] if not e["what"].startswith(PRUNE_STAGES)
    )
    # The reader's reason is the whole raw reason: no comment cut one short.
    raw = {words[0]: " ".join(words[2:]) for words in _named("exception")}
    assert {e["what"]: e["reason"] for e in knob["exception"]} == raw


def test_the_knob_reads_clean() -> None:
    _assert_clean(_read_knob())


def test_a_prune_soak_ending_does_not_turn_the_knob_red() -> None:
    """A prune stage's review-by date is its soak: once it passes, the probe
    reports the component again, which is the prompt for the next stage
    (the skill's pruning.md). The repo's suite must not go red on that date,
    for every unrelated change, while the next stage waits for its window."""
    soaks = [
        date.fromisoformat(words[1])
        for words in _named("exception")
        if words[0].startswith(PRUNE_STAGES)
    ]
    if not soaks:
        pytest.skip("no prune stage declared")
    today = (max(soaks) + timedelta(days=1)).isoformat()
    _assert_clean(_read_knob("--today", today))


def test_no_exception_reason_is_cut_short_by_a_comment() -> None:
    for raw in KNOB.read_text().splitlines():
        if raw.startswith("exception "):
            assert _strip_comment(raw) == " ".join(raw.split()), (
                f"' #' opens a comment, cutting this reason short: {raw}"
            )


def test_the_window_is_the_owners_weekly_slot_in_utc() -> None:
    assert _named("cadence") == [["weekly"]]
    assert _named("window") == [WINDOW]


def _assert_quiet_and_outside_the_window(name: str, first: int, last: int) -> None:
    quiet = [tuple(_minutes(t) for t in q[0].split("-")) for q in _named("quiet") if len(q) == 1]
    assert any(start <= first and last <= end for start, end in quiet), (
        f"{name} starts {first}-{last} min past midnight, and no every-day quiet line covers it"
    )
    w_start, w_end = (_minutes(t) for t in WINDOW[1].split("-"))
    assert last <= w_start or first >= w_end, f"{name} runs inside the window"


def test_the_backup_timer_is_quiet_and_outside_the_window() -> None:
    _assert_quiet_and_outside_the_window(
        "archiver-backup.timer", *_timer_span(DEPLOY / "archiver-backup.timer")
    )


def test_the_temporal_boundary_timer_is_quiet_and_outside_the_window() -> None:
    """``Persistent=`` catches up a missed run, never one a restart killed."""
    _assert_quiet_and_outside_the_window(
        "archiver-temporal-boundary.timer",
        *_timer_span(DEPLOY / "archiver-temporal-boundary.timer"),
    )


def test_the_disk_gc_timer_is_quiet_and_outside_the_window() -> None:
    """Read from the installed layer: the repo carries no copy of it (#440)."""
    if not _on_host():
        pytest.skip(f"{INSTALLED_UNIT} not present: not a host running the service")
    assert GC_TIMER.is_file(), f"{GC_TIMER} missing: the disk GC isn't installed (#440)"
    # The layer invites an OnCalendar= drop-in; one would move the timer off
    # the file read here, so the quiet line would be checked against nothing.
    assert not GC_TIMER_DROPIN.exists(), f"{GC_TIMER_DROPIN}: re-derive the quiet line from it"
    _assert_quiet_and_outside_the_window(GC_TIMER.name, *_timer_span(GC_TIMER))


def test_no_knob_command_escalates_or_reads_production_secrets() -> None:
    commands = _commands("health") + _commands("inflight") + _commands("recovery")
    assert commands, "the knob declares no command"
    for command in commands:
        for word in ("sudo", "runuser", "pkexec", "doas", "su ", "systemd-run"):
            assert word not in command, f"{word!r} in a knob command: {command}"
        for secret in ("/etc/archiver", "ALLOW_PRODUCTION_DB", "DATABASE_URL", "python"):
            assert secret not in command, f"{secret!r} in a knob command: {command}"


def test_inflight_counts_every_oneshot_by_unit_state() -> None:
    (command,) = _commands("inflight")
    assert command == (
        "systemctl list-units 'archiver-*.service' --state=activating,active,deactivating "
        "--no-legend --plain | grep -v '^archiver\\.service' | wc -l"
    )
    services = _timer_services()
    assert services, "deploy/ has no timer"
    for service in services:
        assert service.startswith("archiver-"), f"{service} escapes the inflight glob"
        (unit_type,) = _values((DEPLOY / service).read_text(), "Type")
        assert unit_type == "oneshot", f"{service}: inflight counts oneshots by state"


def test_health_is_the_db_free_route_on_loopback() -> None:
    assert _commands("health") == [
        "curl -sf -m5 http://127.0.0.1:8000/health | jq -e '.status == \"ok\"'"
    ]


def test_recovery_reads_through_the_read_role() -> None:
    (command,) = _commands("recovery")
    assert command.startswith("psql -d archiver -XAtc ")
    assert "information.changes_outbox" in command
    assert command.endswith("| grep -qx 0")


def test_the_backup_stands_in_for_the_archiver_database_alone() -> None:
    assert _named("datastore") == [["postgres", "postgresql@16-main", "archiver"]]
    assert _named("backup") == [["archiver-backup.service", "postgresql@16-main"]]
    (start,) = _values((DEPLOY / "archiver-backup.service").read_text(), "ExecStart")
    assert start.endswith("-m src.core.backup --database archiver")
    excepted = {words[0] for words in _named("exception")}
    assert {"database:archiver_dev", "database:archiver_test"} <= excepted


@pytest.mark.parametrize("unit", _timer_services())
def test_each_timer_service_is_an_unprivileged_non_restarter(unit: str) -> None:
    """The exception is the owner's word; these are the facts it rests on.
    A unit that gains root, or a module that gains ``systemctl``, fails here
    before the knob goes on vouching for it."""
    excepted = {words[0] for words in _named("exception")}
    assert f"not-restarter:{unit}" in excepted
    text = (DEPLOY / unit).read_text()
    assert _values(text, "User") not in ([], ["root"]), f"{unit}: runs as root"
    starts = _values(text, "ExecStart")
    assert all(not start.startswith(("+", "!")) for start in starts), f"{unit}: a root ExecStart"
    for directive in _OTHER_EXEC:
        for line in _values(text, directive):
            assert "systemctl" not in line, f"{unit}: {directive}= calls systemctl"
    for start in starts:
        module = start.split("-m ", 1)[1].split()[0]
        source = (REPO_ROOT / Path(*module.split("."))).with_suffix(".py").read_text()
        assert "systemctl" not in source, f"{unit} runs something that calls systemctl"


def test_no_restarter_is_declared() -> None:
    """No ``OnFailure=``: the liveness heartbeat's silence is the page (#297)."""
    assert _named("restarter") == []
    for unit in DEPLOY.glob("*.service"):
        assert _values(unit.read_text(), "OnFailure") == [], unit.name


def test_the_release_tree_is_the_repos_own() -> None:
    """``/srv/archiver/live`` is a release, with no remote to read (#330)."""
    assert ["/srv/archiver/live", "self"] in _named("owner")


def test_the_service_is_the_runbook_service() -> None:
    assert _named("service") == [["archiver.service"]]


def test_each_followed_origin_has_a_scoping_pin_file() -> None:
    followed = {words[0] for words in _named("origin") if words[1] == "follow"}
    assert followed == set(FOLLOWED)
    for origin, (name, packages) in FOLLOWED.items():
        stanzas = _pins(PINS / name)
        assert all(s["Pin"] == f"origin {origin}" for s in stanzas), name
        by_package = {s["Package"]: int(s["Pin-Priority"]) for s in stanzas}
        assert by_package.pop("*") < 500, f"{name}: the catch-all must sit below 500"
        assert set(" ".join(by_package).split()) == packages
        assert all(priority > 500 for priority in by_package.values()), name


def test_tailscale_restarts_in_its_own_step() -> None:
    assert ["tailscale", "tailscale-archive-keyring", "tailscale"] in _named("hold")


def test_the_one_caller_is_public_and_no_private_name_is_published() -> None:
    assert _named("caller") == [["CannObserv/replicator"]]
    assert _named("image-owner") == []


@pytest.mark.parametrize("name", sorted(name for name, _ in FOLLOWED.values()))
def test_installed_pins_match_tracked(name: str) -> None:
    """Gated on the host, not on the file: gating on the file under test would
    pass silently on exactly the host that never received it."""
    if not _on_host():
        pytest.skip(f"{INSTALLED_UNIT} not present: not a host running the service")
    installed = INSTALLED_PINS / name
    hint = f"Install with:\n  sudo install -m 644 {PINS / name} {installed}"
    assert installed.exists(), f"{installed} is missing.\n{hint}"
    assert installed.read_text() == (PINS / name).read_text(), f"{installed} drifted.\n{hint}"
