"""The Watcher notification-template import (archiver#363, D6).

Keyed by Watcher's template id (``imported_watcher_id``): create if absent,
report ``differs`` and never overwrite, so a re-run lands on the same
subscription ids (#369's idempotency key depends on them). ``--channel-map``
translates Watcher-tenant channels; anything that does not map refuses the
whole file before a write. ``parse_export`` is pure; ``main`` runs against a
fake client.
"""

import io
import json
from types import SimpleNamespace

import pytest
from archiver_client import NotFound

from src.core.tools.import_watcher_notification_templates import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_REFUSED,
    ImportRefused,
    main,
    parse_channel_map,
    parse_export,
)

T1 = "01KQN12MHJJHFETN2XMDF98GT1"
T2 = "01KQN12MHJJHFETN2XMDF98GT2"
T3 = "01KQN12MHJJHFETN2XMDF98GT3"
W_SLACK = "01KQN12MHJJHFETN2XMDF98GHY"
W_MAIL = "01KQN12MHY05FEGK9BCMJMACW8"
W_SINK = "01KQG9DQ51TK7CRWJWBVK6DKDC"
A_SLACK = "01M5AX8CE8PBMQZMQ5TBBB9RAP"
A_MAIL = "01M5AX8CEAEKPM7JJ3D0VY20AF"
MAP = {W_SLACK: A_SLACK, W_MAIL: A_MAIL}
ITEM = "01JA0000000000000000000000"
HOST = "known.example.com"


def _template(tid: str = T1, **overrides) -> dict:
    row = {
        "id": tid,
        "title": "secret-title",
        "channel_hint": "#secret-hint",
        "events": ["change_detected", "watch_error"],
        "visibility": "global",
        "domain_name": None,
        "archiver_info_item_id": None,
        "is_active": True,
        "content_config": None,
        "remote_channel_id": W_SLACK,
    }
    row.update(overrides)
    return row


def _export(templates: list, **top) -> dict:
    doc = {
        "schema_version": 1,
        "source": "watcher",
        "exported_at": "2026-10-14T00:00:00.000000Z",
        "items": {ITEM: {"name": "secret-item-name"}},
        "domains": {"secret.example": {}},
        "notification_templates": templates,
    }
    doc.update(top)
    return doc


# --- parse (pure) ---


def test_a_global_template_maps_onto_a_create_body():
    [wanted] = parse_export(_export([_template()]), MAP)
    assert wanted.watcher_id == T1
    assert wanted.body == {
        "title": "secret-title",
        "scope": "global",
        "events": ["change_detected", "watch_error"],
        "remote_channel_id": A_SLACK,
        "is_active": True,
        "content_config": None,
        "imported_watcher_id": T1,
    }


def test_domain_and_watched_item_scopes_carry_their_ref():
    domain, item = parse_export(
        _export(
            [
                _template(T1, visibility="domain", domain_name=HOST),
                _template(T2, visibility="watched_item", archiver_info_item_id=ITEM),
            ]
        ),
        MAP,
    )
    assert (domain.body["scope"], domain.body["domain"]) == ("domain", HOST)
    assert "info_item_id" not in domain.body
    assert (item.body["scope"], item.body["info_item_id"]) == ("item", ITEM)
    assert "domain" not in item.body


def test_the_retired_content_keys_are_dropped_at_every_level():
    config = {
        "default": {"include_significance": True, "include_domain": True},
        "overrides": {"watch_error": {"include_change_dashboard_url": True}},
    }
    [wanted] = parse_export(_export([_template(content_config=config)]), MAP)
    assert wanted.body["content_config"] == {
        "default": {"include_domain": True},
        "overrides": {"watch_error": {}},
    }


def test_events_are_put_in_declaration_order():
    [wanted] = parse_export(
        _export([_template(events=["watch_recovered", "change_detected"])]), MAP
    )
    assert wanted.body["events"] == ["change_detected", "watch_recovered"]


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_export([_template()], schema_version=2), "schema_version"),
        (_export([_template()], source="replicator"), "source"),
        (_export([_template()], notification_templates={}), "no notification_templates list"),
        (_export(["not an object"]), "not an object"),
        (_export([_template("not-a-ulid")]), "not a template id"),
        (_export([_template(), _template()]), "duplicate"),
        (_export([_template(visibility="team")]), "visibility"),
        (_export([_template(visibility="domain")]), "domain_name"),
        (_export([_template(visibility="watched_item")]), "archiver_info_item_id"),
        (_export([_template(domain_name=HOST)]), "domain_name"),
        (_export([_template(events=[])]), "events"),
        (_export([_template(events=["created"])]), "events"),
        (_export([_template(title="")]), "title"),
        (_export([_template(title="x" * 101)]), "title"),
        (_export([_template(is_active="yes")]), "is_active"),
        (_export([_template(remote_channel_id=W_SINK)]), "not in --channel-map"),
        (_export([_template(remote_channel_id=None)]), "no channel"),
        (_export([_template(content_config={"default": {"surprise": 1}})]), "content_config"),
        (
            _export([_template(content_config={"default": {"body_template": "{% if %}"}})]),
            "content_config",
        ),
    ],
)
def test_anything_that_does_not_map_refuses_the_whole_file(document, match):
    with pytest.raises(ImportRefused, match=match):
        parse_export(document, MAP)


def test_every_problem_is_reported_not_just_the_first():
    with pytest.raises(ImportRefused) as refused:
        parse_export(
            _export([_template(T1, events=[]), _template(T2, remote_channel_id=W_SINK)]), MAP
        )
    assert len(refused.value.problems) == 2


def test_the_channel_map_is_parsed_and_normalized():
    assert parse_channel_map([f"{W_SLACK}={A_SLACK.lower()}"]) == {W_SLACK: A_SLACK}


@pytest.mark.parametrize(
    "pairs",
    [["nope"], [f"{W_SLACK}=dev-sink"], [f"{W_SLACK}={A_SLACK}", f"{W_SLACK}={A_MAIL}"]],
)
def test_a_malformed_channel_map_is_a_value_error(pairs):
    with pytest.raises(ValueError):
        parse_channel_map(pairs)


# --- main, against a fake client ---


class FakeClient:
    """The SDK calls the importer makes, over in-memory tables."""

    def __init__(self, subs=None, domains=(HOST,), items=(ITEM,)):
        self.subs: list[dict] = list(subs or [])
        self.domains = set(domains)
        self.items = set(items)
        self.writes: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get_domain(self, name):
        if name not in self.domains:
            raise NotFound("Domain not found", status_code=404)
        return SimpleNamespace(name=name)

    async def get_info_item(self, info_item_id):
        if info_item_id not in self.items:
            raise NotFound("InfoItem not found", status_code=404)
        return SimpleNamespace(info_item_id=info_item_id)

    async def list_notification_subscriptions(self, *, limit=None, offset=None):
        offset = offset or 0
        rows = self.subs[offset : offset + limit]
        return SimpleNamespace(
            items=[SimpleNamespace(to_dict=lambda r=r: dict(r)) for r in rows],
            has_more=offset + limit < len(self.subs),
        )

    async def create_notification_subscription(self, body):
        self.writes.append(body)
        row = {
            "id": f"01SUB{len(self.subs):021d}",
            "domain": None,
            "info_item_id": None,
            **body,
        }
        self.subs.append(row)
        return SimpleNamespace(id=row["id"])


def _run(document, client, *args, environ=None, channel_map=MAP):
    out, err = io.StringIO(), io.StringIO()
    maps = [arg for w, a in channel_map.items() for arg in ("--channel-map", f"{w}={a}")]
    code = main(
        ["--base-url", "http://localhost:8001", *maps, *args],
        stdin=io.StringIO(json.dumps(document)),
        stdout=out,
        stderr=err,
        environ={"ARCHIVER_API_KEY": "k"} if environ is None else environ,
        client_factory=lambda **kw: client,
    )
    return code, out.getvalue(), err.getvalue()


def _two_globals() -> dict:
    return _export(
        [
            _template(T1),
            _template(
                T2,
                remote_channel_id=W_MAIL,
                content_config={"default": {"include_significance": False}},
            ),
        ]
    )


def test_dry_run_prints_the_plan_and_writes_nothing():
    client = FakeClient()

    code, out, _err = _run(_two_globals(), client, "--dry-run")

    assert code == EXIT_OK
    assert client.writes == []
    assert f"create {T1}: global scope" in out
    assert f"create {T2}: global scope" in out
    assert "2 to create, 0 differ, 0 unchanged (dry run)" in out
    for secret in ("secret-title", "#secret-hint", "secret-item-name", "secret.example"):
        assert secret not in out


def test_a_real_run_creates_and_a_rerun_lands_on_the_same_rows():
    client = FakeClient()

    code, out, _err = _run(_two_globals(), client)

    assert code == EXIT_OK
    assert [w["imported_watcher_id"] for w in client.writes] == [T1, T2]
    assert client.writes[1]["remote_channel_id"] == A_MAIL
    assert client.writes[1]["content_config"] == {"default": {}}
    assert "2 created, 0 differ, 0 unchanged" in out

    client.writes.clear()
    code, out, _err = _run(_two_globals(), client)
    assert (code, client.writes) == (EXIT_OK, [])
    assert "0 created, 0 differ, 2 unchanged" in out
    assert len(client.subs) == 2


def test_an_existing_row_that_differs_is_reported_and_kept():
    existing = {
        "id": "01SUBEXISTING0000000000000",
        "title": "renamed in Archiver",
        "scope": "global",
        "domain": None,
        "info_item_id": None,
        "events": ["change_detected"],
        "remote_channel_id": A_SLACK,
        "is_active": True,
        "content_config": {"default": {"include_domain": True}},
        "imported_watcher_id": T1,
    }
    client = FakeClient(subs=[existing])

    code, out, _err = _run(_export([_template(T1)]), client)

    assert (code, client.writes) == (EXIT_OK, [])
    assert f"differs on {T1} (as 01SUBEXISTING0000000000000)" in out
    assert "title, events, content_config" in out
    assert "0 created, 1 differ, 0 unchanged" in out


def test_default_content_options_compare_equal_to_none():
    existing = {
        "id": "01SUBEXISTING0000000000000",
        "title": "secret-title",
        "scope": "global",
        "domain": None,
        "info_item_id": None,
        "events": ["change_detected", "watch_error"],
        "remote_channel_id": A_SLACK,
        "is_active": True,
        "content_config": None,
        "imported_watcher_id": T1,
    }
    client = FakeClient(subs=[existing])
    document = _export([_template(T1, content_config={"default": {"diff_snippet_lines": 25}})])

    code, out, _err = _run(document, client)

    assert code == EXIT_OK
    assert "0 created, 0 differ, 1 unchanged" in out


def test_existing_subscriptions_are_read_across_pages():
    filler = [
        {"id": f"01SUBFILL{n:017d}", "imported_watcher_id": None, "title": "x"} for n in range(600)
    ]
    keyed = {
        "id": "01SUBEXISTING0000000000000",
        "title": "secret-title",
        "scope": "global",
        "domain": None,
        "info_item_id": None,
        "events": ["change_detected", "watch_error"],
        "remote_channel_id": A_SLACK,
        "is_active": True,
        "content_config": None,
        "imported_watcher_id": T1,
    }
    client = FakeClient(subs=[*filler, keyed])

    code, out, _err = _run(_export([_template(T1)]), client)

    assert (code, client.writes) == (EXIT_OK, [])
    assert "1 unchanged" in out


def test_an_unknown_domain_or_item_refuses_before_any_write():
    client = FakeClient(domains=(), items=())
    document = _export(
        [
            _template(T1),
            _template(T2, visibility="domain", domain_name="gone.example.com"),
            _template(T3, visibility="watched_item", archiver_info_item_id=ITEM),
        ]
    )

    code, _out, err = _run(document, client)

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert f"{T2}: no Domain row" in err
    assert f"{T3}: InfoItem {ITEM} not in Archiver" in err


def test_an_unmapped_channel_refuses_the_whole_file():
    client = FakeClient()

    code, _out, err = _run(_two_globals(), client, channel_map={W_SLACK: A_SLACK})

    assert (code, client.writes) == (EXIT_REFUSED, [])
    assert f"{T2}: channel {W_MAIL} is not in --channel-map" in err


def test_a_malformed_channel_map_is_an_error():
    code, _out, err = _run(_two_globals(), FakeClient(), channel_map={W_SLACK: "dev-sink"})
    assert code == EXIT_ERROR
    assert "--channel-map" in err


@pytest.mark.parametrize("stdin_text", ["not json", "[]"])
def test_input_that_is_not_an_export_is_an_error(stdin_text):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--base-url", "http://localhost:8001"],
        stdin=io.StringIO(stdin_text),
        stdout=out,
        stderr=err,
        environ={"ARCHIVER_API_KEY": "k"},
        client_factory=lambda **kw: FakeClient(),
    )
    assert code == EXIT_ERROR
    assert "not a JSON export" in err.getvalue()


def test_no_api_key_is_an_error():
    code, _out, err = _run(_two_globals(), FakeClient(), environ={})
    assert code == EXIT_ERROR
    assert "ARCHIVER_API_KEY" in err


def test_base_url_is_required():
    with pytest.raises(SystemExit):
        main([], stdin=io.StringIO("{}"), environ={"ARCHIVER_API_KEY": "k"})
