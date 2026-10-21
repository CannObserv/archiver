"""audit_stored_documents — re-judge every stored authored document (archiver#164).

Each authored JSONB document is validated on write and never again. A schema
tightening therefore strands rows that still publish - the announcement path
checks only the envelope - but cannot be re-saved, because every edit path
re-validates the whole document. The WSLCB Meeting Schedule source sat that way
with a ``target`` key #48 had dropped, found only when someone tried an edit.

The sweep runs each stored document through the validator its write path uses,
so "will this round-trip?" has an answer before anyone needs one. ``KINDS`` is
the registry; ``tests/core/tools/test_audit_stored_documents.py`` fails when a
``src/core/*_schema/`` function or a JSON column is neither swept here nor
listed in an exemption with its reason.

The rule this backs (docs/CONVENTIONS.md): a tightening ships with a data
migration, or with this sweep's "0 affected" recorded in the PR - and for
RepSpecs only drafts may be migrated, because an assigned document is frozen
(#83).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import Select, false, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.core.models import InfoItem, InfoItemRepSpec, InfoSource, RepSpec
from src.core.rep_fields_schema.validator import linked_org_key_errors, validate_rep_fields
from src.core.rep_spec_schema.validator import validate_rep_spec
from src.core.source_spec_schema.families import families_of
from src.core.source_spec_schema.validator import ValidationError, validate_source_spec
from src.core.watch_spec_schema.validator import validate_watch_spec


@dataclass(frozen=True, slots=True)
class Finding:
    """One stored document the current validator rejects.

    ``index`` is the position in a list column (``source_specs``), ``None`` for
    a whole-column finding. ``frozen`` is set for an assigned RepSpec, whose
    document cannot be edited (#83): the remedy is a clone, not an edit, and
    until then it cannot gain assignments (#334).
    """

    kind: str
    row_id: str
    index: int | None
    errors: list[ValidationError]
    frozen: bool = False


@dataclass(frozen=True, slots=True)
class AuditReport:
    """The sweep's result: every finding, and how many documents were judged."""

    findings: list[Finding]
    checked: int


@dataclass(frozen=True, slots=True)
class DocumentKind:
    """One authored document column, the validators its write paths apply, and how to sweep it.

    ``query`` selects ``(row_id, document, flag)`` per row, ordered by primary
    key; ``judge`` turns one such row into findings. ``flag`` is the row context
    a kind needs - linked for ``rep_fields``, frozen for ``rep_spec`` - and
    ``false`` otherwise. ``per_entry`` counts each entry of a list column as a
    document of its own (``source_specs``).
    """

    name: str
    column: InstrumentedAttribute
    validators: tuple[Callable[..., object], ...]
    query: Select
    judge: Callable[[str, object, bool], list[Finding]]
    per_entry: bool = False

    def documents(self, document: object) -> int:
        """How many documents ``document`` counts as in the sweep's total."""
        if self.per_entry and isinstance(document, list) and document:
            return len(document)
        return 1


def error_text(error: ValidationError) -> str:
    """``path: message``, without the bare ``/`` a whole-document error carries."""
    if error["path"] in ("", "/"):
        return error["message"]
    return f"{error['path']}: {error['message']}"


# ---------------------------------------------------------------------------
# Per-row judgement - shared by the sweep and the detail-page notices
# ---------------------------------------------------------------------------


def _errors(validate: Callable[[object], tuple[bool, list[ValidationError]]], document: object):
    """``validate``'s errors, or one error naming the exception it raised.

    A validator can raise on a document malformed enough - ``validate_rep_spec``
    does on a non-string ``provider``. The write path would 500 on that row, so
    it cannot round-trip either, and one such row must not blind the sweep to
    the rest.
    """
    try:
        return validate(document)[1]
    except Exception as e:  # noqa: BLE001 - any raise is the finding
        return [{"path": "", "message": f"validator raised {type(e).__name__}: {e}"}]


def _source_specs_findings(row_id: str, specs: object) -> list[Finding]:
    """The checks ``update_info_source_specs`` runs before it writes: each entry, then the mix."""
    if not isinstance(specs, list) or not specs:
        message = "at least one spec is required" if specs == [] else "must be a JSON array"
        return [Finding("source_spec", row_id, None, [{"path": "", "message": message}])]
    findings = [
        Finding("source_spec", row_id, i, errors)
        for i, spec in enumerate(specs)
        if (errors := _errors(validate_source_spec, spec))
    ]
    if findings:
        return findings
    # Only once every entry validates, as the write path orders it (#356 D3).
    families = families_of(spec["extraction"]["algorithm"] for spec in specs)
    if len(families) > 1:
        message = f"source_specs mix content-kind families: {sorted(families)!r}"
        return [Finding("source_spec", row_id, None, [{"path": "", "message": message}])]
    return []


def _watch_spec_findings(row_id: str, document: object) -> list[Finding]:
    errors = _errors(validate_watch_spec, document)
    return [Finding("watch_spec", row_id, None, errors)] if errors else []


def _rep_fields_findings(row_id: str, bag: object, *, linked: bool) -> list[Finding]:
    """Shape, plus the org-owned keys ``set_rep_fields`` refuses while linked (#304)."""
    errors = _errors(validate_rep_fields, bag)
    if linked and isinstance(bag, dict):
        errors = errors + linked_org_key_errors(bag)
    return [Finding("rep_fields", row_id, None, errors)] if errors else []


def _rep_spec_findings(row_id: str, document: object, *, frozen: bool) -> list[Finding]:
    errors = _errors(validate_rep_spec, document)
    return [Finding("rep_spec", row_id, None, errors, frozen=frozen)] if errors else []


def info_source_findings(src: InfoSource) -> list[Finding]:
    """The stored ``source_specs`` of one InfoSource, judged as the sweep judges it."""
    return _source_specs_findings(str(src.info_source_id), src.source_specs)


def info_item_findings(item: InfoItem) -> list[Finding]:
    """One InfoItem's ``watch_spec`` and ``rep_fields``, judged as the sweep judges them."""
    row_id = str(item.info_item_id)
    return _watch_spec_findings(row_id, item.watch_spec) + _rep_fields_findings(
        row_id, item.rep_fields, linked=item.pm_org_id is not None
    )


def rep_spec_findings(spec: RepSpec, *, frozen: bool) -> list[Finding]:
    """One RepSpec's document; ``frozen`` is whether it has any assignment row (#83)."""
    return _rep_spec_findings(str(spec.rep_spec_id), spec.document, frozen=frozen)


# ---------------------------------------------------------------------------
# The registry - each kind's query and judge
# ---------------------------------------------------------------------------


def _judge_source_specs(row_id: str, specs: object, _flag: bool) -> list[Finding]:
    return _source_specs_findings(row_id, specs)


def _judge_watch_spec(row_id: str, document: object, _flag: bool) -> list[Finding]:
    return _watch_spec_findings(row_id, document)


def _judge_rep_fields(row_id: str, bag: object, linked: bool) -> list[Finding]:
    return _rep_fields_findings(row_id, bag, linked=linked)


def _judge_rep_spec(row_id: str, document: object, frozen: bool) -> list[Finding]:
    return _rep_spec_findings(row_id, document, frozen=frozen)


_ASSIGNED = select(InfoItemRepSpec.rep_spec_id).distinct().scalar_subquery()

KINDS: tuple[DocumentKind, ...] = (
    DocumentKind(
        "source_spec",
        InfoSource.source_specs,
        (validate_source_spec, families_of),
        select(InfoSource.info_source_id, InfoSource.source_specs, false()).order_by(
            InfoSource.info_source_id
        ),
        _judge_source_specs,
        per_entry=True,
    ),
    DocumentKind(
        "watch_spec",
        InfoItem.watch_spec,
        (validate_watch_spec,),
        select(InfoItem.info_item_id, InfoItem.watch_spec, false()).order_by(InfoItem.info_item_id),
        _judge_watch_spec,
    ),
    DocumentKind(
        "rep_fields",
        InfoItem.rep_fields,
        (validate_rep_fields, linked_org_key_errors),
        select(
            InfoItem.info_item_id, InfoItem.rep_fields, InfoItem.pm_org_id.is_not(None)
        ).order_by(InfoItem.info_item_id),
        _judge_rep_fields,
    ),
    DocumentKind(
        "rep_spec",
        RepSpec.document,
        (validate_rep_spec,),
        select(RepSpec.rep_spec_id, RepSpec.document, RepSpec.rep_spec_id.in_(_ASSIGNED)).order_by(
            RepSpec.rep_spec_id
        ),
        _judge_rep_spec,
    ),
)
"""Every authored document column. Adding a schema or a JSON column means adding
a kind here or an exemption below - the guard test refuses neither."""

EXEMPT_VALIDATORS: dict[str, str] = {
    "src.core.rep_fields_schema.validator.validate_rep_fields_against_spec": (
        "judges a bag against an assigned RepSpec, not the stored document alone; "
        "assignment refusals surface on the InfoItem's RepSpec picker"
    ),
    "src.core.rep_fields_schema.validator.check_required_fields": (
        "the presence half of validate_rep_fields_against_spec; same reason"
    ),
    "src.core.source_spec_schema.families.family_for": (
        "applied through families_of, the list rule the write paths and this sweep call"
    ),
}
"""Public ``*_schema`` functions the sweep deliberately does not apply, with why."""

EXEMPT_COLUMNS: dict[str, str] = {
    "changes_outbox.payload": "a wire record already published, not an authored document",
    "replication_commands.object_options": (
        "a copy of a RepSpec's object_options taken at issuance; a wire record"
    ),
}
"""JSON columns that hold no authored document, with why."""


async def audit_stored_documents(db: AsyncSession) -> AuditReport:
    """Judge every stored document of every kind against its current validator.

    One full-column read per kind: the corpus is tens of documents, and the
    dashboard runs this once per home-page load, never on a poll. Findings come
    in ``KINDS`` order and by primary key within a kind, so the list page reads
    the same on every load.
    """
    checked, findings = 0, []
    for kind in KINDS:
        for row_id, document, flag in await db.execute(kind.query):
            checked += kind.documents(document)
            findings.extend(kind.judge(str(row_id), document, flag))
    return AuditReport(findings=findings, checked=checked)


# ---------------------------------------------------------------------------
# The export path - production's documents, judged without Python touching it
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_ERROR = 2


def export_sql() -> str:
    """One statement printing every document row as a JSON line: ``[kind, id, doc, flag]``.

    Compiled from each kind's own ``query``, so the export reads exactly what
    the sweep reads and cannot drift from it. Ordered like the sweep - kind,
    then primary key - so ``judge_exported`` returns the same report.
    """
    parts = []
    for ordinal, kind in enumerate(KINDS):
        inner = kind.query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        parts.append(
            f"SELECT {ordinal} AS k, q.c0 AS rid, "
            f"json_build_array('{kind.name}', q.c0, q.c1, q.c2)::text AS line "
            f"FROM ({inner}) AS q(c0, c1, c2)"
        )
    union = "\nUNION ALL\n".join(parts)
    return f"SELECT line FROM (\n{union}\n) AS export ORDER BY k, rid;"


def judge_exported(lines: Iterable[str]) -> AuditReport:
    """Judge ``export_sql``'s output, line by line, as the sweep judges the table.

    Blank lines are skipped. Raises ``ValueError`` on a line that is not a
    ``[kind, id, document, flag]`` array or names no kind in ``KINDS``.
    """
    by_name = {k.name: k for k in KINDS}
    checked, findings = 0, []
    for line in lines:
        if not line.strip():
            continue
        name, row_id, document, flag = json.loads(line)
        kind = by_name.get(name)
        if kind is None:
            raise ValueError(f"unknown kind {name!r}")
        checked += kind.documents(document)
        findings.extend(kind.judge(str(row_id), document, bool(flag)))
    return AuditReport(findings=findings, checked=checked)


def _finding_line(finding: Finding) -> str:
    where = f"[{finding.index}]" if finding.index is not None else ""
    frozen = " (frozen: assigned, clone to fix)" if finding.frozen else ""
    messages = "; ".join(error_text(e) for e in finding.errors)
    return f"{finding.kind} {finding.row_id}{where}{frozen}: {messages}"


def main(argv: list[str] | None = None, *, stdin=None, stdout=None, stderr=None) -> int:
    """``--sql`` prints the export statement; otherwise judge an export read from stdin.

    The "0 affected" check a schema tightening records (docs/CONVENTIONS.md),
    run against production without a production URL in Python::

        set -o pipefail
        psql -d archiver -At -c "$(uv run python -m src.core.tools.audit_stored_documents --sql)" \\
          | uv run python -m src.core.tools.audit_stored_documents

    Exit 0 when every document validates, 1 when any does not, 2 on input that
    is not an export - including an empty one. A psql that failed prints nothing
    to stdout, and without ``pipefail`` the pipeline reports this exit alone, so
    no rows must never read as "0 affected" (CR 10).
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--sql", action="store_true", help="print the export statement")
    args = parser.parse_args(argv)
    if args.sql:
        print(export_sql(), file=stdout)
        return EXIT_OK
    try:
        report = judge_exported(stdin)
    except (ValueError, TypeError) as e:
        print(f"not an export_sql() line: {e}", file=stderr)
        return EXIT_ERROR
    if report.checked == 0:
        print("empty export - did psql fail? (every row counts at least one document)", file=stderr)
        return EXIT_ERROR
    for finding in report.findings:
        print(_finding_line(finding), file=stdout)
    print(f"{report.checked} documents checked, {len(report.findings)} invalid", file=stdout)
    return EXIT_INVALID if report.findings else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
