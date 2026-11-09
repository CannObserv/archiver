"""The Watcher item-tag import (archiver#362, D6).

Fill-if-empty: Watcher's ``default_tags`` are written only where Archiver's item
has none. An item already tagged in Archiver is ``differs`` and left alone;
one the export names but Archiver lacks is ``missing`` and skipped. Any tag
breaking D2's rule refuses the whole file, naming the item ids. Only ids and
counts reach the output: the export is root-only and the repos are public.
The plan is pure; ``main`` runs against a fake client.
"""

import io
import json
from types import SimpleNamespace

import pytest
from archiver_client import NotFound

from src.core.tools.import_watcher_item_tags import (
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
E = "01JE0000000000000000000000"


def _item(tags=None, **overrides) -> dict:
    row = {
        "name": "secret-name",
        "description": "secret-description",
        "default_tags": tags,
        "default_schedule_config": None,
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


# --- parse and plan (pure) ---


def test_only_items_with_watcher_tags_are_considered_normalized():
    document = _export(
        {A: _item(None), B: _item([]), C: _item([" zeta", "Alpha", "zeta"])},
    )
    assert parse_export(document) == {C: ["Alpha", "zeta"]}


def test_an_empty_archiver_set_is_filled_and_a_tagged_one_is_kept():
    steps = plan(
        {A: ["a"], B: ["b"], C: ["c"], D: ["d"]},
        {A: [], B: ["other"], C: ["c"], D: None},
    )
    by_id = {s.info_item_id: s for s in steps}

    assert (by_id[A].action, by_id[A].tags) == ("fill", ["a"])
    assert by_id[B].action == "differs"
    assert by_id[C].action == "unchanged"
    assert by_id[D].action == "missing"


def test_an_archived_watcher_item_imports_like_any_other():
    """D3: tags are allowed on an archived item; archive is watch-only."""
    document = _export({A: _item(["a"], archived_at="2026-10-20T00:00:00Z")})
    assert parse_export(document) == {A: ["a"]}


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_export({A: _item(["a"])}, schema_version=2), "schema_version"),
        (_export({A: _item(["a"])}, source="replicator"), "source"),
        (_export({A: _item(["a"])}, items=[]), "no items object"),
        (_export({"not-a-ulid": _item(["a"])}), "not an InfoItem id"),
        (_export({A: "not an object"}), "not an object"),
        (_export({A: {"name": "x"}}), "missing 'default_tags'"),
        (_export({A: _item("a")}), "not a list"),
    ],
)
def test_anything_that_does_not_map_refuses_the_whole_file(document, match):
    with pytest.raises(ImportRefused, match=match):
        parse_export(document)


def test_a_tag_breaking_the_rule_refuses_the_whole_file_naming_only_ids():
    document = _export(
        {
            A: _item(["fine"]),
            B: _item(["has,comma-secret"]),
            C: _item(["x" * 256]),
        }
    )

    with pytest.raises(ImportRefused, match="2 item\\(s\\) with tags breaking") as refused:
        parse_export(document)
    message = str(refused.value)
    assert B in message and C in message
    assert A not in message
    assert "secret" not in message and "x" * 256 not in message


# --- main, against a fake client ---


class FakeClient:
    """The two SDK calls the importer makes, over an in-memory table."""

    def __init__(self, rows: dict[str, list[str]]):
        self.rows = rows
        self.writes: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_info_item(self, info_item_id):
        if info_item_id not in self.rows:
            raise NotFound("InfoItem not found", status_code=404)
        return SimpleNamespace(tags=list(self.rows[info_item_id]))

    async def set_tags(self, info_item_id, tags):
        self.writes.append((info_item_id, tags))
        self.rows[info_item_id] = sorted(set(tags))


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


def _prod_like() -> dict[str, list[str]]:
    return {A: [], B: ["archiver-own"], C: ["same"], E: []}


def _document() -> dict:
    return _export(
        {
            A: _item(["secret-tag", "another"]),
            B: _item(["secret-watcher"]),
            C: _item(["same"]),
            D: _item(["secret-missing"]),
            E: _item(None),
        }
    )


def test_dry_run_prints_ids_and_counts_and_writes_nothing():
    client = FakeClient(_prod_like())

    code, out, _err = _run(_document(), client, "--dry-run")

    assert code == EXIT_OK
    assert client.writes == []
    assert f"fill {A}: 2 tag(s)" in out
    assert f"differs on {B}: kept Archiver's 1 tag(s) (Watcher 1)" in out
    assert f"unchanged {C}" in out
    assert f"missing {D}: not in Archiver, skipped" in out
    assert E not in out
    assert "1 to fill, 1 differ, 1 unchanged, 1 missing (dry run)" in out
    for secret in ("secret", "another", "same", "do-not-print"):
        assert secret not in out


def test_a_real_run_fills_only_and_a_rerun_is_a_no_op():
    client = FakeClient(_prod_like())

    code, out, _err = _run(_document(), client)

    assert code == EXIT_OK
    assert client.writes == [(A, ["another", "secret-tag"])]
    assert "1 filled, 1 differ, 1 unchanged, 1 missing" in out

    client.writes.clear()
    code, out, _err = _run(_document(), client)
    assert (code, client.writes) == (EXIT_OK, [])
    assert "0 filled, 1 differ, 2 unchanged, 1 missing" in out


def test_a_refused_file_writes_nothing_and_exits_refused():
    client = FakeClient(_prod_like())
    document = _export({A: _item(["ok"]), B: _item(["bad\nsecret"])})

    code, out, err = _run(document, client)

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert "refused:" in err and B in err
    assert "secret" not in err + out


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
