"""Tests for the stored-document sweep (archiver#164).

Every authored JSONB document is written through a validator, but nothing
re-reads what is already stored. A schema tightening therefore leaves rows that
publish cleanly and cannot be re-saved - the ``target`` key on the WSLCB
Meeting Schedule source was one. The sweep re-judges each stored document
against the validator its write path uses, and the structural guard below keeps
the registry from going stale the next time a schema or column is added.
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import pkgutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import JSON, text
from ulid import ULID

from src.core.models import InfoItem, InfoItemRepSpec, InfoSource, RepSpec
from src.core.models.base import Base
from src.core.models.pm_organization import PmOrganization
from src.core.tools.audit_stored_documents import (
    EXEMPT_COLUMNS,
    EXEMPT_VALIDATORS,
    KINDS,
    DocumentKind,
    audit_stored_documents,
    export_sql,
    info_item_findings,
    info_source_findings,
    judge_exported,
    rep_spec_findings,
)
from src.core.tools.audit_stored_documents import (
    main as cli_main,
)

_CORE = Path(__file__).resolve().parents[3] / "src" / "core"


def _valid_spec() -> dict:
    return {"schema_version": 1, "extraction": {"algorithm": "full_page"}, "fingerprint": {}}


def _legacy_spec() -> dict:
    """The production row #164 was filed for: a ``target`` key the schema dropped in #48."""
    return {
        "target": {"url": "https://lcb.wa.gov/boardmeetings/board_meetings"},
        "extraction": {"selector": "div.content", "algorithm": "css"},
        "fingerprint": {},
        "schema_version": 1,
    }


def _gcs_doc(**object_options) -> dict:
    return {
        "provider": "gcs",
        "credentials_alias": "gcs-prod",
        "path_template": "archive/{info_item.slug}/{source_revision.fingerprint}.html",
        "required_fields": ["info_item.slug"],
        "object_options": object_options or {"storage_class": "STANDARD"},
    }


def _org(pm_org_id: str) -> PmOrganization:
    now = datetime.now(UTC)
    return PmOrganization(
        pm_org_id=pm_org_id, name="Org", active=True, pm_updated_at=now, checked_at=now
    )


def _mine(findings, *ids) -> list:
    """Findings for rows this test created - the tables are shared across the run."""
    wanted = {str(i) for i in ids}
    return [f for f in findings if f.row_id in wanted]


# ---------------------------------------------------------------------------
# The sweep finds a seeded invalid document of each kind
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_finds_invalid_source_spec_at_its_index(session):
    src = InfoSource(url="https://example.com/a164", source_specs=[_valid_spec(), _legacy_spec()])
    session.add(src)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, src.info_source_id)
    assert finding.kind == "source_spec"
    assert finding.index == 1
    assert "'target' was unexpected" in finding.errors[0]["message"]


@pytest.mark.asyncio
async def test_sweep_finds_empty_source_specs_list(session):
    """The write paths refuse an empty list, so a stored one cannot round-trip either."""
    src = InfoSource(url="https://example.com/b164", source_specs=[])
    session.add(src)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, src.info_source_id)
    assert finding.kind == "source_spec"
    assert finding.index is None


@pytest.mark.asyncio
async def test_sweep_finds_invalid_watch_spec(session):
    # ``active`` in the document is the mistake the watch_spec schema exists to refuse.
    item = InfoItem(name="w164", watch_spec={"schema_version": 1, "active": False})
    session.add(item)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, item.info_item_id)
    assert finding.kind == "watch_spec"
    assert finding.index is None


@pytest.mark.asyncio
async def test_sweep_finds_off_shape_rep_fields(session):
    item = InfoItem(name="r164", rep_fields={"slug": "flat-key"})
    session.add(item)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, item.info_item_id)
    assert finding.kind == "rep_fields"


@pytest.mark.asyncio
async def test_sweep_finds_org_owned_key_on_a_linked_item(session):
    """``set_rep_fields`` refuses ``org.title`` while linked, so the stored bag is frozen too."""
    session.add(_org("01KPMORG164LINKED00000000A"))
    await session.flush()
    item = InfoItem(
        name="l164", rep_fields={"org": {"title": "Shadow"}}, pm_org_id="01KPMORG164LINKED00000000A"
    )
    session.add(item)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, item.info_item_id)
    assert finding.kind == "rep_fields"
    assert finding.errors[0]["path"] == "/org/title"


@pytest.mark.asyncio
async def test_unlinked_item_may_carry_org_title(session):
    item = InfoItem(name="u164", rep_fields={"org": {"title": "Typed"}})
    session.add(item)
    await session.flush()

    report = await audit_stored_documents(session)

    assert _mine(report.findings, item.info_item_id) == []


@pytest.mark.asyncio
async def test_sweep_finds_invalid_draft_rep_spec(session):
    spec = RepSpec(provider="gcs", name="d164", schema_version=1, document=_gcs_doc(folder_id="x"))
    session.add(spec)
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, spec.rep_spec_id)
    assert finding.kind == "rep_spec"
    assert finding.frozen is False


@pytest.mark.asyncio
async def test_invalid_assigned_rep_spec_is_reported_frozen(session):
    """#83: an assigned document cannot be edited, so the remedy is a clone, not an edit."""
    spec = RepSpec(provider="gcs", name="f164", schema_version=1, document=_gcs_doc(folder_id="x"))
    item = InfoItem(name="fi164")
    session.add_all([spec, item])
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
            deactivated_at=datetime.now(UTC),
        )
    )
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, spec.rep_spec_id)
    assert finding.frozen is True


@pytest.mark.asyncio
async def test_a_document_the_validator_raises_on_is_a_finding_not_a_crash(session):
    """``validate_rep_spec`` raises ``TypeError`` on a non-string ``provider``.

    One such row must not blind the sweep to every other row - and the write
    path would 500 on it, so it cannot round-trip either.
    """
    bad = RepSpec(provider="gcs", name="raise164", schema_version=1, document={"provider": 5})
    legacy = InfoSource(url="https://example.com/c164", source_specs=[_legacy_spec()])
    session.add_all([bad, legacy])
    await session.flush()

    report = await audit_stored_documents(session)

    [finding] = _mine(report.findings, bad.rep_spec_id)
    assert finding.errors[0]["message"].startswith("validator raised TypeError")
    assert _mine(report.findings, legacy.info_source_id)


@pytest.mark.asyncio
async def test_findings_come_in_kind_then_id_order_not_insertion_order(session):
    """The list page must not reshuffle between loads (CR 4)."""
    later = InfoSource(
        info_source_id=ULID.from_str("01KZZZZZZZZZZZZZZZZZZZZ164"),
        url="https://example.com/o2-164",
        source_specs=[_legacy_spec()],
    )
    earlier = InfoSource(
        info_source_id=ULID.from_str("01KAAAAAAAAAAAAAAAAAAAA164"),
        url="https://example.com/o1-164",
        source_specs=[_legacy_spec()],
    )
    item = InfoItem(name="o164", watch_spec={"schema_version": 1, "active": False})
    session.add(later)
    await session.flush()
    session.add_all([item, earlier])
    await session.flush()

    report = await audit_stored_documents(session)

    mine = _mine(report.findings, later.info_source_id, earlier.info_source_id, item.info_item_id)
    assert [f.row_id for f in mine] == [
        str(earlier.info_source_id),
        str(later.info_source_id),
        str(item.info_item_id),
    ]


@pytest.mark.asyncio
async def test_valid_documents_produce_no_findings_and_are_counted(session):
    before = await audit_stored_documents(session)
    src = InfoSource(url="https://example.com/v164", source_specs=[_valid_spec(), _valid_spec()])
    item = InfoItem(name="v164", rep_fields={"info_item": {"slug": "v"}})
    spec = RepSpec(provider="gcs", name="v164", schema_version=1, document=_gcs_doc())
    session.add_all([src, item, spec])
    await session.flush()

    report = await audit_stored_documents(session)

    assert _mine(report.findings, src.info_source_id, item.info_item_id, spec.rep_spec_id) == []
    # Two specs, a watch_spec, a rep_fields bag, a RepSpec document.
    assert report.checked == before.checked + 5


# ---------------------------------------------------------------------------
# Per-row checks for the detail notices: same judgement, no sweep
# ---------------------------------------------------------------------------


def test_row_checks_agree_with_the_sweep_kinds():
    src = InfoSource(url="https://example.com/x", source_specs=[_legacy_spec()])
    item = InfoItem(name="x", watch_spec={"schema_version": 1, "active": True}, rep_fields={})
    spec = RepSpec(provider="gcs", name="x", schema_version=1, document=_gcs_doc(folder_id="x"))

    assert [f.kind for f in info_source_findings(src)] == ["source_spec"]
    assert [f.kind for f in info_item_findings(item)] == ["watch_spec"]
    assert [(f.kind, f.frozen) for f in rep_spec_findings(spec, frozen=True)] == [
        ("rep_spec", True)
    ]


# ---------------------------------------------------------------------------
# Structural guard: the registry covers every validator and every JSON column
# ---------------------------------------------------------------------------


def _schema_functions() -> set[str]:
    """Every public function defined in a ``src/core/*_schema/`` package, as ``module.name``."""
    found: set[str] = set()
    for pkg_dir in sorted(_CORE.glob("*_schema")):
        pkg = f"src.core.{pkg_dir.name}"
        for info in pkgutil.iter_modules([str(pkg_dir)]):
            module = importlib.import_module(f"{pkg}.{info.name}")
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if not name.startswith("_") and obj.__module__ == module.__name__:
                    found.add(f"{module.__name__}.{name}")
    return found


def _json_columns() -> set[str]:
    """Every JSON/JSONB column on the ORM models, as ``table.column``."""
    return {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, JSON)
    }


def registry_gaps(kinds: tuple[DocumentKind, ...]) -> list[str]:
    """What a schema or column added without a sweep decision looks like."""
    used = {f"{fn.__module__}.{fn.__name__}" for k in kinds for fn in k.validators}
    covered = {f"{k.column.class_.__tablename__}.{k.column.key}" for k in kinds}
    gaps = [
        f"validator {name} is neither swept nor exempt"
        for name in sorted(_schema_functions() - used - set(EXEMPT_VALIDATORS))
    ]
    gaps += [
        f"column {name} is neither swept nor exempt"
        for name in sorted(_json_columns() - covered - set(EXEMPT_COLUMNS))
    ]
    return gaps


def test_registry_covers_every_schema_validator_and_json_column():
    assert registry_gaps(KINDS) == []


@pytest.mark.parametrize("dropped", [k.name for k in KINDS])
def test_guard_fails_when_a_kind_is_removed(dropped):
    assert registry_gaps(tuple(k for k in KINDS if k.name != dropped))


def test_guard_sees_the_four_kinds():
    """The enumeration itself works - an empty scan would pass the guard vacuously."""
    assert {
        "src.core.source_spec_schema.validator.validate_source_spec",
        "src.core.watch_spec_schema.validator.validate_watch_spec",
        "src.core.rep_fields_schema.validator.validate_rep_fields",
        "src.core.rep_spec_schema.validator.validate_rep_spec",
    } <= _schema_functions()
    assert {
        "info_sources.source_specs",
        "info_items.watch_spec",
        "info_items.rep_fields",
        "rep_specs.document",
    } <= _json_columns()


def test_exemptions_are_live_and_reasoned():
    """A stale exemption is a hole the next schema can walk through unnoticed."""
    for name, reason in {**EXEMPT_VALIDATORS, **EXEMPT_COLUMNS}.items():
        assert reason.strip(), name
    assert set(EXEMPT_VALIDATORS) <= _schema_functions()
    assert set(EXEMPT_COLUMNS) <= _json_columns()


# ---------------------------------------------------------------------------
# The export path: production's documents judged without Python touching it
# ---------------------------------------------------------------------------


async def _seed_one_invalid_of_each_kind(session) -> None:
    session.add(_org("01KPMORG164EXPORT00000000A"))
    await session.flush()
    spec = RepSpec(provider="gcs", name="e164", schema_version=1, document=_gcs_doc(folder_id="x"))
    item = InfoItem(
        name="e164",
        watch_spec={"schema_version": 1, "active": False},
        rep_fields={"org": {"title": "Shadow"}},
        pm_org_id="01KPMORG164EXPORT00000000A",
    )
    session.add_all(
        [
            InfoSource(
                url="https://example.com/e164", source_specs=[_valid_spec(), _legacy_spec()]
            ),
            RepSpec(provider="gcs", name="r164", schema_version=1, document={"provider": 5}),
            spec,
            item,
        ]
    )
    await session.flush()
    session.add(
        InfoItemRepSpec(
            info_item_id=item.info_item_id,
            rep_spec_id=spec.rep_spec_id,
            activated_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def _export_lines(session) -> list[str]:
    """What ``psql -At -c "$(… --sql)"`` prints: one JSON line per document row."""
    return list((await session.execute(text(export_sql()))).scalars())


@pytest.mark.asyncio
async def test_exported_rows_judge_exactly_as_the_sweep(session):
    """The export is compiled from each kind's own query, so it cannot drift from the sweep."""
    await _seed_one_invalid_of_each_kind(session)

    swept = await audit_stored_documents(session)
    exported = judge_exported(await _export_lines(session))

    assert exported == swept
    assert {f.kind for f in exported.findings} >= {k.name for k in KINDS}
    assert any(f.frozen for f in exported.findings)


def test_judge_exported_refuses_an_unknown_kind():
    with pytest.raises(ValueError, match="unknown kind"):
        judge_exported(['["nope", "01K", {}, false]'])


def test_cli_prints_the_export_sql():
    out = io.StringIO()
    assert cli_main(["--sql"], stdin=io.StringIO(), stdout=out) == 0
    assert out.getvalue().strip() == export_sql().strip()


@pytest.mark.asyncio
async def test_cli_exits_1_and_names_each_finding(session):
    await _seed_one_invalid_of_each_kind(session)
    lines = await _export_lines(session)
    out = io.StringIO()

    code = cli_main([], stdin=io.StringIO("\n".join(lines) + "\n\n"), stdout=out)

    assert code == 1
    assert "'target' was unexpected" in out.getvalue()
    assert "frozen" in out.getvalue()
    assert out.getvalue().rstrip().endswith("invalid")


def test_cli_exits_0_when_every_document_validates():
    line = json.dumps(["watch_spec", "01KVALID", {"schema_version": 1}, False])
    out = io.StringIO()
    assert cli_main([], stdin=io.StringIO(line + "\n"), stdout=out) == 0
    assert "1 documents checked, 0 invalid" in out.getvalue()


def test_cli_exits_2_on_a_malformed_line():
    out = io.StringIO()
    assert cli_main([], stdin=io.StringIO("not json\n"), stdout=out) == 2


@pytest.mark.parametrize("pkg_dir", sorted(_CORE.glob("*_schema")), ids=lambda p: p.name)
def test_every_schema_validator_points_at_the_tightening_rule(pkg_dir):
    """Whoever tightens a schema edits this module; the rule has to be where they look (CR 3)."""
    doc = importlib.import_module(f"src.core.{pkg_dir.name}.validator").__doc__ or ""
    assert "Schema tightenings" in doc and "archiver#164" in doc


@pytest.mark.parametrize("stdin", ["", "\n\n"], ids=["empty", "blank-lines"])
def test_cli_refuses_an_empty_export(stdin):
    """CR 10. A failed psql prints nothing to stdout; without pipefail the
    pipeline's status is the judge's, so an empty export must not read as
    "0 affected" - that is the evidence a tightening PR records."""
    out, err = io.StringIO(), io.StringIO()
    assert cli_main([], stdin=io.StringIO(stdin), stdout=out, stderr=err) == 2
    assert "0 invalid" not in out.getvalue()
    assert "empty export" in err.getvalue()
