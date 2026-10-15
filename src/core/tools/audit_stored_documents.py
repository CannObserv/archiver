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

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.core.models import InfoItem, InfoItemRepSpec, InfoSource, RepSpec
from src.core.rep_fields_schema.validator import linked_org_key_errors, validate_rep_fields
from src.core.rep_spec_schema.validator import validate_rep_spec
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
    """One authored document column, the validators its write paths apply, and its sweep."""

    name: str
    column: InstrumentedAttribute
    validators: tuple[Callable[..., object], ...]
    sweep: Callable[[AsyncSession], Awaitable[tuple[int, list[Finding]]]]


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
    """The checks ``update_info_source_specs`` runs before it writes."""
    if not isinstance(specs, list) or not specs:
        message = "at least one spec is required" if specs == [] else "must be a JSON array"
        return [Finding("source_spec", row_id, None, [{"path": "", "message": message}])]
    return [
        Finding("source_spec", row_id, i, errors)
        for i, spec in enumerate(specs)
        if (errors := _errors(validate_source_spec, spec))
    ]


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
# The sweep - one query per kind, whole column
# ---------------------------------------------------------------------------


def _collect(
    rows: Iterable[tuple], judge: Callable[..., list[Finding]], size: Callable[[object], int]
) -> tuple[int, list[Finding]]:
    checked, findings = 0, []
    for row_id, document, *rest in rows:
        checked += size(document)
        findings.extend(judge(str(row_id), document, *rest))
    return checked, findings


def _one(_document: object) -> int:
    return 1


async def _sweep_source_specs(db: AsyncSession) -> tuple[int, list[Finding]]:
    rows = await db.execute(
        select(InfoSource.info_source_id, InfoSource.source_specs).order_by(
            InfoSource.info_source_id
        )
    )
    return _collect(
        rows, _source_specs_findings, lambda s: len(s) if isinstance(s, list) and s else 1
    )


async def _sweep_watch_specs(db: AsyncSession) -> tuple[int, list[Finding]]:
    rows = await db.execute(
        select(InfoItem.info_item_id, InfoItem.watch_spec).order_by(InfoItem.info_item_id)
    )
    return _collect(rows, _watch_spec_findings, _one)


async def _sweep_rep_fields(db: AsyncSession) -> tuple[int, list[Finding]]:
    rows = await db.execute(
        select(
            InfoItem.info_item_id, InfoItem.rep_fields, InfoItem.pm_org_id.is_not(None)
        ).order_by(InfoItem.info_item_id)
    )
    return _collect(rows, lambda i, bag, linked: _rep_fields_findings(i, bag, linked=linked), _one)


async def _sweep_rep_specs(db: AsyncSession) -> tuple[int, list[Finding]]:
    assigned = select(InfoItemRepSpec.rep_spec_id).distinct().scalar_subquery()
    rows = await db.execute(
        select(RepSpec.rep_spec_id, RepSpec.document, RepSpec.rep_spec_id.in_(assigned)).order_by(
            RepSpec.rep_spec_id
        )
    )
    return _collect(rows, lambda i, doc, frozen: _rep_spec_findings(i, doc, frozen=frozen), _one)


KINDS: tuple[DocumentKind, ...] = (
    DocumentKind(
        "source_spec", InfoSource.source_specs, (validate_source_spec,), _sweep_source_specs
    ),
    DocumentKind("watch_spec", InfoItem.watch_spec, (validate_watch_spec,), _sweep_watch_specs),
    DocumentKind(
        "rep_fields",
        InfoItem.rep_fields,
        (validate_rep_fields, linked_org_key_errors),
        _sweep_rep_fields,
    ),
    DocumentKind("rep_spec", RepSpec.document, (validate_rep_spec,), _sweep_rep_specs),
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
        "the mixed-family list rule; one family exists today, so no stored list can mix. "
        "A second family is a tightening the rule covers"
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
        n, found = await kind.sweep(db)
        checked += n
        findings.extend(found)
    return AuditReport(findings=findings, checked=checked)
