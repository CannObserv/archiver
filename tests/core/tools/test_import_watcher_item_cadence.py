"""The Watcher item-cadence import (archiver#364, D3).

Fill-if-absent: Watcher's own item cadence is written only where Archiver's item
has no ``interval``. Archiver's announced value already wins at Watcher's top
tier, so it is what runs today, and overwriting it would change a live cadence.
The plan is pure; ``main`` runs against a fake client.
"""

import io
import json
from types import SimpleNamespace

import pytest
from archiver_client import NotFound

from src.core.tools.import_watcher_item_cadence import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_REFUSED,
    ImportRefused,
    main,
    parse_export,
    plan,
)

A = "01JA0000000000000000000000"
B = "01JB0000000000000000000000"
C = "01JC0000000000000000000000"
D = "01JD0000000000000000000000"


def _item(cadence=None, **overrides) -> dict:
    row = {
        "name": "secret-name",
        "description": None,
        "default_tags": [],
        "default_schedule_config": cadence,
        "announced_schedule_config": None,
        "throttle_floor_interval": None,
        "archived_at": None,
        "temporal_profile": None,
    }
    row.update(overrides)
    return row


def _export(rows: dict, **top) -> dict:
    doc = {
        "schema_version": 1,
        "source": "watcher",
        "exported_at": "2026-10-14T00:00:00.000000Z",
        "items": rows,
        "domains": {"secret.example": {}},
        "notification_templates": [{"remote_channel_id": "do-not-print"}],
    }
    doc.update(top)
    return doc


# --- plan (pure) ---


def test_only_items_with_a_watcher_cadence_are_considered():
    assert parse_export(_export({A: _item(), B: _item({"interval": "1d"})})) == {B: "1d"}


def test_an_absent_archiver_interval_is_filled_and_a_set_one_is_kept():
    steps = plan(
        {A: "1d", B: "6h", C: "1h", D: "1d"},
        {
            A: {"schema_version": 1},
            B: {"schema_version": 1, "interval": "1h"},
            C: {"schema_version": 1, "interval": "1h"},
            D: None,  # not in Archiver
        },
    )
    by_id = {s.info_item_id: s for s in steps}

    assert by_id[A].action == "fill"
    assert by_id[A].document == {"schema_version": 1, "interval": "1d"}
    assert (by_id[B].action, by_id[B].archiver_interval) == ("differs", "1h")
    assert by_id[C].action == "unchanged"
    assert by_id[D].action == "missing"


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_export({A: _item()}, schema_version=2), "schema_version"),
        (_export({A: _item()}, source="replicator"), "source"),
        (_export({A: _item()}, items=[]), "no items object"),
        (_export({"not-a-ulid": _item({"interval": "1d"})}), "not an InfoItem id"),
        (_export({A: _item({"interval": "1d", "cron": "x"})}), "is not"),
        (_export({A: _item({"interval": "daily"})}), "default_schedule_config"),
        (_export({A: "not an object"}), "not an object"),
        (_export({A: {"name": "x"}}), "missing"),
    ],
)
def test_anything_that_does_not_map_refuses_the_whole_file(document, match):
    with pytest.raises(ImportRefused, match=match):
        parse_export(document)


# --- main, against a fake client ---


class FakeClient:
    """The two SDK calls the importer makes, over an in-memory table."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self.writes: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_info_item(self, info_item_id):
        if info_item_id not in self.rows:
            raise NotFound("InfoItem not found", status_code=404)
        spec = self.rows[info_item_id]
        return SimpleNamespace(watch_spec=SimpleNamespace(to_dict=lambda: dict(spec)))

    async def set_watch_spec(self, info_item_id, document):
        self.writes.append((info_item_id, document))
        self.rows[info_item_id] = document


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
    return {
        A: {"schema_version": 1},
        B: {"schema_version": 1, "interval": "1h"},
        C: {"schema_version": 1, "interval": "6h"},
    }


def _document() -> dict:
    return _export(
        {
            A: _item({"interval": "1d"}),
            B: _item({"interval": "6h"}),
            C: _item({"interval": "6h"}),
            D: _item({"interval": "1d"}),
            "01JE0000000000000000000000": _item(),
        }
    )


def test_dry_run_prints_the_plan_and_writes_nothing():
    client = FakeClient(_prod_like())

    code, out, _err = _run(_document(), client, "--dry-run")

    assert code == EXIT_OK
    assert client.writes == []
    assert f"fill {A}: interval '1d'" in out
    assert f"differs on {B}: kept Archiver's '1h' (Watcher '6h')" in out
    assert f"unchanged {C}" in out
    assert f"missing {D}: not in Archiver, skipped" in out
    assert "1 to fill, 1 differ, 1 unchanged, 1 missing (dry run)" in out
    for secret in ("secret-name", "secret.example", "do-not-print"):
        assert secret not in out


def test_a_real_run_fills_only_and_a_rerun_is_a_no_op():
    client = FakeClient(_prod_like())

    code, out, _err = _run(_document(), client)

    assert code == EXIT_OK
    assert client.writes == [(A, {"schema_version": 1, "interval": "1d"})]
    assert "1 filled, 1 differ, 1 unchanged, 1 missing" in out

    client.writes.clear()
    code, out, _err = _run(_document(), client)
    assert (code, client.writes) == (EXIT_OK, [])
    assert "0 filled, 1 differ, 2 unchanged, 1 missing" in out


def test_a_refused_file_writes_nothing_and_exits_refused():
    client = FakeClient(_prod_like())
    document = _export({A: _item({"interval": "1d"}), B: _item({"interval": "soon"})})

    code, _out, err = _run(document, client)

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert "refused:" in err


@pytest.mark.parametrize("stdin_text", ["not json", "[]"])
def test_input_that_is_not_an_export_is_an_error(stdin_text):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--base-url", "http://localhost:8001"],
        stdin=io.StringIO(stdin_text),
        stdout=out,
        stderr=err,
        environ={"ARCHIVER_API_KEY": "k"},
        client_factory=lambda **kw: FakeClient({}),
    )
    assert code == EXIT_ERROR
    assert "not a JSON export" in err.getvalue()


def test_no_api_key_is_an_error_before_anything_is_read():
    code, _out, err = _run(_document(), FakeClient({}), environ={})
    assert code == EXIT_ERROR
    assert "ARCHIVER_API_KEY" in err


def test_base_url_is_required():
    with pytest.raises(SystemExit):
        main([], stdin=io.StringIO("{}"), environ={"ARCHIVER_API_KEY": "k"})


def test_an_archived_watcher_item_refuses_the_whole_file_naming_the_count():
    """archiver#361 D5: archive is authored in Archiver now, so an archived item in
    the export is refused, not imported - even one with no cadence to import."""
    document = _export(
        {
            A: _item({"interval": "1d"}),
            B: _item(archived_at="2026-10-20T00:00:00Z"),
            C: _item(archived_at="2026-10-21T00:00:00Z"),
        }
    )

    with pytest.raises(ImportRefused, match="2 archived") as refused:
        parse_export(document)
    assert B in str(refused.value) and C in str(refused.value)
    assert A not in str(refused.value)


def test_a_refused_archive_exits_refused_and_writes_nothing():
    client = FakeClient(_prod_like())
    document = _export({A: _item({"interval": "1d"}, archived_at="2026-10-20T00:00:00Z")})

    code, _out, err = _run(document, client, "--dry-run")

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert "1 archived" in err
