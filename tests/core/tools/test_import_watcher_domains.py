"""The Watcher domain import (archiver#360, design D4).

The plan is pure and tested on its own: what each host's diff is, what is
refused. ``main`` is tested against a fake client - the API it drives has its
own tests - for the properties an operator relies on: a dry run writes nothing,
a refused file writes nothing, a re-run is a no-op, and nothing but the domains
slice reaches stdout.
"""

import io
import json
from types import SimpleNamespace

import pytest

from src.core.tools.import_watcher_domains import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_REFUSED,
    Current,
    ImportRefused,
    main,
    plan,
)


def _watcher(**overrides) -> dict:
    row = {
        "min_interval": 1,
        "default_schedule_config": None,
        "notes": None,
        "is_active": True,
        "archived_at": None,
    }
    row.update(overrides)
    return row


def _export(domains: dict, **top) -> dict:
    doc = {
        "schema_version": 1,
        "source": "watcher",
        "exported_at": "2026-10-14T00:00:00.000000Z",
        "items": {"secret-item": {"notifier_channel": "do-not-print"}},
        "domains": domains,
        "notification_templates": [{"remote_channel_id": "do-not-print"}],
    }
    doc.update(top)
    return doc


def _current(**overrides) -> Current:
    values = {
        "notes": None,
        "is_active": True,
        "archived": False,
        "min_interval_seconds": 1.0,
        "default_watch_spec": None,
    }
    values.update(overrides)
    return Current(**values)


# --- plan (pure) ---


def test_hosts_already_matching_need_nothing_and_a_new_one_is_created():
    steps = plan(
        _export({"a.example": _watcher(), "new.example": _watcher()}),
        {"a.example": _current()},
    )
    by_host = {s.name: s for s in steps}

    assert by_host["a.example"].changed is False
    assert by_host["new.example"].create is True
    assert by_host["new.example"].patch == {"min_interval_seconds": 1.0}


def test_watcher_wins_for_active():
    (step,) = plan(_export({"a.example": _watcher(is_active=False)}), {"a.example": _current()})
    assert step.patch == {"is_active": False}


def test_archivers_live_interval_and_cadence_are_kept_and_reported():
    """D5 and D5' (archiver#364): since F1 the interval, and since #364 the
    cadence, are what runs - Archiver's. A differing Watcher value is reported."""
    (step,) = plan(
        _export(
            {"a.example": _watcher(min_interval=2.5, default_schedule_config={"interval": "6h"})}
        ),
        {"a.example": _current(default_watch_spec={"schema_version": 1, "interval": "1d"})},
    )
    assert step.patch == {}
    assert step.changed is False
    assert (step.interval_conflict, step.cadence_conflict) == (True, True)


def test_a_null_watcher_cadence_leaves_archivers_and_reports_it():
    (step,) = plan(
        _export({"a.example": _watcher()}),
        {"a.example": _current(default_watch_spec={"schema_version": 1, "interval": "1d"})},
    )
    assert step.patch == {}
    assert step.cadence_conflict is True


def test_a_watcher_cadence_fills_an_empty_archiver_default():
    (step,) = plan(
        _export({"a.example": _watcher(default_schedule_config={"interval": "6h"})}),
        {"a.example": _current()},
    )
    assert step.patch == {"default_watch_spec": {"schema_version": 1, "interval": "6h"}}
    assert step.cadence_conflict is False


def test_a_new_host_takes_watchers_interval_and_cadence():
    (step,) = plan(
        _export(
            {"new.example": _watcher(min_interval=2.5, default_schedule_config={"interval": "6h"})}
        ),
        {},
    )
    assert step.create is True
    assert step.patch == {
        "min_interval_seconds": 2.5,
        "default_watch_spec": {"schema_version": 1, "interval": "6h"},
    }


def test_archived_ness_follows_watcher():
    archive, restore = plan(
        _export(
            {
                "a.example": _watcher(archived_at="2026-10-01T00:00:00.000000Z"),
                "b.example": _watcher(),
            }
        ),
        {"a.example": _current(), "b.example": _current(archived=True)},
    )
    assert (archive.archive, restore.archive) == ("archive", "restore")


def test_notes_fill_an_empty_field_and_never_overwrite_a_different_one():
    fill, keep, same = plan(
        _export(
            {
                "a.example": _watcher(notes="from watcher"),
                "b.example": _watcher(notes="from watcher"),
                "c.example": _watcher(notes="same"),
            }
        ),
        {
            "a.example": _current(),
            "b.example": _current(notes="archiver's own"),
            "c.example": _current(notes="same"),
        },
    )
    assert fill.patch == {"notes": "from watcher"}
    assert (keep.patch, keep.notes_conflict) == ({}, True)
    assert (same.changed, same.notes_conflict) == (False, False)


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_export({}, schema_version=2), "schema_version"),
        (_export({}, source="replicator"), "source"),
        ({"schema_version": 1, "source": "watcher"}, "domains"),
        (_export({"a.example": _watcher(min_interval=-1)}), "min_interval"),
        (_export({"a.example": _watcher(min_interval="1")}), "min_interval"),
        (_export({"a.example": _watcher(min_interval=True)}), "min_interval"),
        (_export({"a.example": _watcher(min_interval=10**400)}), "min_interval"),  # CR 19
        (
            _export({"a.example": _watcher(default_schedule_config={"interval": "6 hours"})}),
            "6 hours",
        ),
        (
            _export({"a.example": _watcher(default_schedule_config={"interval": "6h", "x": 1})}),
            "default_schedule_config",
        ),
        (_export({"a.example": _watcher(default_schedule_config={})}), "default_schedule_config"),
        (_export({"a.example": _watcher(is_active="yes")}), "is_active"),
        (_export({"a.example": _watcher(notes=3)}), "notes"),
        (_export({"a.example": _watcher(archived_at=1)}), "archived_at"),
        (_export({"a.example": {"min_interval": 1}}), "missing"),
        (_export({"https://a.example/": _watcher()}), "host"),
    ],
)
def test_anything_that_does_not_map_refuses_the_whole_file(document, match):
    with pytest.raises(ImportRefused, match=match):
        plan(document, {})


def test_every_problem_is_reported_not_just_the_first():
    with pytest.raises(ImportRefused) as refused:
        plan(
            _export({"a.example": _watcher(min_interval=-1), "b.example": _watcher(notes=3)}),
            {},
        )
    assert len(refused.value.problems) == 2


# --- main, against a fake client ---


class FakeClient:
    """The four SDK calls the importer makes, over an in-memory table."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self.writes: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_domains(self, *, limit=None, offset=None):
        names = sorted(self.rows)[offset : offset + limit]
        items = [self._out(n) for n in names]
        return SimpleNamespace(items=items, has_more=offset + limit < len(self.rows))

    def _out(self, name):
        r = self.rows[name]
        spec = r["default_watch_spec"]
        return SimpleNamespace(
            name=name,
            notes=r["notes"],
            is_active=r["is_active"],
            archived_at="2026-10-24T00:00:00Z" if r["archived"] else None,
            min_interval_seconds=r["min_interval_seconds"],
            default_watch_spec=None if spec is None else SimpleNamespace(to_dict=lambda: spec),
        )

    async def upsert_domain(self, name, **fields):
        self.writes.append(("upsert", name, fields))
        row = self.rows.setdefault(name, dict(vars(_current())))
        row.update(fields)

    async def archive_domain(self, name):
        self.writes.append(("archive", name))
        self.rows[name]["archived"] = True

    async def restore_domain(self, name):
        self.writes.append(("restore", name))
        self.rows[name]["archived"] = False


def _run(document, client, *args, environ=None):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--base-url", "http://localhost:8001", *args],
        stdin=io.StringIO(json.dumps(document)),
        stdout=out,
        stderr=err,
        environ={"ARCHIVER_API_KEY": "k"} if environ is None else environ,
        client_factory=lambda **kw: client,
    )
    return code, out.getvalue(), err.getvalue()


def _prod_like() -> dict[str, dict]:
    return {n: dict(vars(_current())) for n in ("a.example", "b.example", "c.example")}


def test_dry_run_prints_the_diff_and_writes_nothing():
    client = FakeClient(_prod_like())
    hosts = ("a.example", "b.example", "c.example", "d.example")
    document = _export({n: _watcher() for n in hosts})

    code, out, _err = _run(document, client, "--dry-run")

    assert code == EXIT_OK
    assert client.writes == []
    assert "create d.example" in out
    assert "1 to create, 0 to update, 3 unchanged" in out
    assert "do-not-print" not in out and "secret-item" not in out


def test_a_real_run_applies_the_plan_and_a_rerun_is_a_no_op():
    client = FakeClient(_prod_like())
    document = _export(
        {
            "a.example": _watcher(min_interval=2),
            "b.example": _watcher(archived_at="2026-10-01T00:00:00Z"),
            "c.example": _watcher(),
            "d.example": _watcher(),
        }
    )

    code, out, _err = _run(document, client)

    assert code == EXIT_OK
    assert client.writes == [
        ("archive", "b.example"),
        ("upsert", "d.example", {"min_interval_seconds": 1.0}),
    ]
    assert "min_interval_seconds differs on a.example: kept Archiver's 1.0 (Watcher 2.0)" in out
    assert "1 created, 1 updated, 2 unchanged" in out

    client.writes.clear()
    code, out, _err = _run(document, client)
    assert (code, client.writes) == (EXIT_OK, [])
    assert "0 created, 0 updated, 4 unchanged" in out


def test_archivers_cadence_is_never_cleared_and_the_difference_is_printed():
    rows = _prod_like()
    rows["a.example"]["default_watch_spec"] = {"schema_version": 1, "interval": "1d"}
    client = FakeClient(rows)

    _code, out, _err = _run(_export({"a.example": _watcher()}), client)

    assert client.writes == []
    assert "default cadence differs on a.example: kept Archiver's '1d' (Watcher None)" in out


def test_a_refused_file_writes_nothing_and_exits_refused():
    client = FakeClient(_prod_like())
    document = _export({"a.example": _watcher(min_interval=2), "z.example": _watcher(notes=3)})

    code, _out, err = _run(document, client)

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert "z.example" in err and "notes" in err


@pytest.mark.parametrize("stdin_text", ["", "not json", "[]"])
def test_input_that_is_not_an_export_is_an_error(stdin_text):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--base-url", "http://localhost:8001", "--dry-run"],
        stdin=io.StringIO(stdin_text),
        stdout=out,
        stderr=err,
        environ={"ARCHIVER_API_KEY": "k"},
        client_factory=lambda **kw: FakeClient({}),
    )
    assert code == EXIT_ERROR


def test_no_api_key_is_an_error_before_anything_is_read():
    code, _out, err = _run(_export({}), FakeClient({}), environ={})
    assert code == EXIT_ERROR
    assert "ARCHIVER_API_KEY" in err


def test_base_url_is_required():
    with pytest.raises(SystemExit):
        main([], stdin=io.StringIO("{}"), stdout=io.StringIO(), stderr=io.StringIO())
