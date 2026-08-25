"""Unit tests for the conftest production-URL safety guard."""

import os

import pytest

from tests.conftest import _OUTBOUND_SERVICE_ENV_VARS, _check_test_url_safety
from tests.outbound_env_audit import (
    _OUTBOUND_ENV_ALLOWLIST,
    SCANNED_ROOTS,
    env_names_read_under,
    outbound_shaped,
    unresolvable_env_reads_under,
)


def test_guard_raises_when_test_url_matches_archiver_database_url(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="must not equal ARCHIVER_DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_raises_when_test_url_matches_database_url(monkeypatch):
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    with pytest.raises(RuntimeError, match="must not equal DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_raises_on_archiver_database_url_even_when_database_url_differs(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/other_db")
    with pytest.raises(RuntimeError, match="must not equal ARCHIVER_DATABASE_URL"):
        _check_test_url_safety("postgresql+asyncpg://host/prod_archiver")


def test_guard_passes_when_test_url_differs_from_both(monkeypatch):
    monkeypatch.setenv("ARCHIVER_DATABASE_URL", "postgresql+asyncpg://host/prod_archiver")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://host/other_db")
    _check_test_url_safety("postgresql+asyncpg://host/archiver_test")  # no exception


def test_guard_passes_when_no_prod_urls_set(monkeypatch):
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _check_test_url_safety("postgresql+asyncpg://host/archiver_test")  # no exception


def test_outbound_service_env_is_scrubbed():
    """The test process must never hold a live outbound-service address (#157).

    On 2026-08-13 a suite run with /etc/archiver/.env sourced provisioned 108
    real WatchedItems into production watcher: the ``client`` fixture runs the
    full app lifespan, the lifespan built a real WatcherClient from
    WATCHER_BASE_URL/WATCHER_API_KEY, and provisioning routes made real POSTs —
    HTTP side effects, so the savepoint fixture that keeps the DB and (it turned
    out) the bus clean could not contain them. Same failure class as
    watcher#233: a test process silently inheriting a production resource from a
    sourced env file.

    That exact route is gone — archiver#142 deleted the SDK, so no lifespan can
    build a Watcher client and no route can POST to it. The list this iterates
    is now the Redis surface plus the two systemd-only gates. The guard is kept
    against the *class* of failure, which outlived its first instance.

    conftest scrubs the whole outbound surface at import, before any fixture
    runs. A test that needs one of these sets it explicitly via monkeypatch —
    which is also why this test asserting absence stays correct: monkeypatch
    restores on teardown.
    """
    for var in _OUTBOUND_SERVICE_ENV_VARS:
        assert var not in os.environ, (
            f"{var} leaked into the test process — the conftest scrub is the only "
            f"thing between a test run and production (#157)"
        )


# --- Outbound env-var registry drift (#157) -------------------------------
#
# test_outbound_service_env_is_scrubbed above iterates the tuple, so it can only
# see variables someone remembered to put IN the tuple. A newly added outbound
# integration whose env var never made the list is invisible to it: the scrub
# silently does not cover the new variable and no test goes red.
#
# That is not hypothetical. It is exactly how CannObserv/watcher#277 happened -
# watcher's notifier client reads NOTIFIER_BASE_URL/NOTIFIER_API_KEY straight
# from os.environ, its conftest scrubs the bus vars but never gained those two,
# and a prod-sourced pytest run dispatches to production notifier with the
# production key, silently and successfully. Archiver's own #157 was the same
# shape under a different name (WATCHER_BASE_URL). The route that caused #157 is
# gone since #142, but the *registry* can drift again the moment archiver grows
# its next outbound integration (Replicator, #169).
#
# These tests close that by inverting the direction: instead of asserting the
# listed vars are absent, derive the outbound surface from src/ and assert every
# member of it is accounted for.


def test_scanner_reads_direct_environ_access(tmp_path):
    """All three os.environ spellings are found."""
    (tmp_path / "m.py").write_text(
        "import os\n"
        "a = os.environ.get('ALPHA_URL')\n"
        "b = os.getenv('BETA_URL')\n"
        "c = os.environ['GAMMA_URL']\n"
    )
    assert env_names_read_under(tmp_path) == {"ALPHA_URL", "BETA_URL", "GAMMA_URL"}


def test_scanner_resolves_constant_indirection_across_modules(tmp_path):
    """A name-mediated read still resolves to the variable it names.

    src/core/db_safety.py defines ALLOW_PRODUCTION_DB_ENV and src/api/main.py
    reads os.environ.get(ALLOW_PRODUCTION_DB_ENV). A scanner that only matched
    string literals would miss it - and missing a read is how this whole guard
    fails open.
    """
    (tmp_path / "defs.py").write_text("GATE_ENV = 'DELTA_TOKEN'\n")
    (tmp_path / "use.py").write_text(
        "import os\nfrom .defs import GATE_ENV\nx = os.environ.get(GATE_ENV)\n"
    )
    assert "DELTA_TOKEN" in env_names_read_under(tmp_path)


def test_scanner_ignores_non_environ_calls(tmp_path):
    """Only os.environ/os.getenv reads count, not any dict .get with a string."""
    (tmp_path / "m.py").write_text("d = {}\nx = d.get('NOT_AN_ENV_URL')\n")
    assert env_names_read_under(tmp_path) == set()


def test_outbound_shaped_classifies_by_name_suffix():
    """Resource-addressing names are outbound; tuning knobs and flags are not."""
    assert outbound_shaped("NOTIFIER_BASE_URL")
    assert outbound_shaped("WATCHER_API_KEY")
    assert outbound_shaped("SOME_DSN")
    assert not outbound_shaped("ARCHIVER_REDIS_STREAM_MAXLEN")
    assert not outbound_shaped("BUILD_ID")


def test_every_outbound_env_var_is_accounted_for():
    """Fitness function: no outbound-addressing env var may go unregistered.

    Every resource-addressing variable read inside the pytest process must be
    either scrubbed by conftest or carry an explicit written reason for being
    exempt. Adding one and forgetting the scrub is the failure this turns red
    (#157, and the same class as CannObserv/watcher#277).

    To fix a failure here: add the variable to _OUTBOUND_SERVICE_ENV_VARS in
    tests/conftest.py, or - if a test process genuinely may hold it - to
    _OUTBOUND_ENV_ALLOWLIST with the reason it is safe.
    """
    unaccounted = {
        name
        for root in SCANNED_ROOTS
        for name in env_names_read_under(root)
        if outbound_shaped(name)
        and name not in _OUTBOUND_SERVICE_ENV_VARS
        and name not in _OUTBOUND_ENV_ALLOWLIST
    }
    assert not unaccounted, (
        f"outbound-addressing env var(s) read in-process but neither scrubbed nor "
        f"allowlisted: {sorted(unaccounted)}. A test process that inherits one "
        f"from /etc/archiver/.env reaches the real resource (#157)."
    )


def test_no_env_read_escapes_static_resolution():
    """Every in-process environment read must resolve to a nameable variable.

    The registry guard above can only classify names it can resolve. A computed
    argument resolves to none, so it would pass that guard by being invisible to
    it rather than by being safe - the same fail-open shape the guard exists to
    remove. Keep reads spelled as a literal or a module-level constant.
    """
    unresolvable = [site for root in SCANNED_ROOTS for site in unresolvable_env_reads_under(root)]
    assert not unresolvable, (
        f"environment read(s) whose variable name cannot be resolved statically: "
        f"{unresolvable}. test_every_outbound_env_var_is_accounted_for cannot "
        f"classify these, so an outbound var hidden behind one is unguarded (#157). "
        f"Either spell the read as a string literal or a module-level constant, or "
        f"- if the dynamic form is genuinely needed - teach _env_names_from in "
        f"tests/outbound_env_audit.py to resolve it. Do not weaken this assertion: "
        f"an unresolvable read passes the registry guard by being invisible to it, "
        f"not by being safe."
    )


def test_scanner_reports_every_value_a_colliding_constant_name_takes(tmp_path):
    """A constant name defined twice must yield BOTH variables, not the last one.

    CR round 1, finding 1. The first implementation kept one flat name -> literal
    map, so two modules defining the same constant collided and the later file
    won: the earlier module's read resolved to the wrong variable and the real
    one was never recorded - a hole, in the guard whose whole job is not to have
    one. Over-reporting is the only safe direction here; a spurious registry
    entry is visible and cheap, a swallowed read is neither.
    """
    (tmp_path / "a_defs.py").write_text(
        "import os\nGATE = 'NOTIFIER_API_KEY'\nx = os.environ.get(GATE)\n"
    )
    (tmp_path / "z_defs.py").write_text("import os\nGATE = 'BUILD_ID'\ny = os.environ.get(GATE)\n")
    names = env_names_read_under(tmp_path)
    assert {"NOTIFIER_API_KEY", "BUILD_ID"} <= names


def test_unresolvable_env_read_is_reported(tmp_path):
    """A computed env-var name is reported, not silently dropped.

    CR round 1, finding 3. os.environ.get(f'{p}_API_KEY') resolves to no literal,
    and returning nothing made an unscannable read indistinguishable from no read
    at all. The guard cannot classify what it cannot name, so it says so instead.
    """
    (tmp_path / "m.py").write_text(
        "import os\np = 'NOTIFIER'\nx = os.environ.get(f'{p}_API_KEY')\n"
    )
    reports = unresolvable_env_reads_under(tmp_path)
    assert len(reports) == 1
    assert "m.py:3" in reports[0]


def test_resolvable_reads_are_not_reported_as_unresolvable(tmp_path):
    """The literal and constant-mediated spellings stay silent."""
    (tmp_path / "m.py").write_text(
        "import os\nGATE = 'ALPHA_URL'\na = os.environ.get('BETA_URL')\nb = os.environ.get(GATE)\n"
    )
    assert unresolvable_env_reads_under(tmp_path) == []


def test_scanned_roots_cover_what_executes_in_the_test_process():
    """alembic/ is in scope because conftest runs it in-process.

    CR round 1, finding 2. tests/conftest.py runs alembic_command.upgrade in an
    executor thread, so alembic/env.py reads the environment inside the test
    process exactly as src/ does. Scanning only src/ left a file that genuinely
    runs under pytest outside the guard.
    """
    names = {p.name for p in SCANNED_ROOTS}
    assert names == {"src", "alembic"}
    for root in SCANNED_ROOTS:
        assert root.is_dir(), f"{root} does not exist - the scan would silently cover nothing"


def test_every_allowlist_entry_states_a_reason():
    """An exemption without a written reason is not re-checkable.

    CR round 1, finding 4. Only key membership was ever consulted, so an entry
    added with an empty string satisfied the 'with the reason' contract that
    docs/DEPLOYMENT.md and the failure message both advertise.
    """
    for name, reason in _OUTBOUND_ENV_ALLOWLIST.items():
        assert reason and reason.strip(), (
            f"{name} is allowlisted with no stated reason - name the mechanism "
            f"that contains it, so the exemption can be re-checked when that "
            f"mechanism changes"
        )
