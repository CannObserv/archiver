"""How the dashboard names a stored-document finding (archiver#164).

The sweep (``src/core/tools/audit_stored_documents``) says *what* fails; this
says where the operator goes to fix it and what fixing it means. The remedy
differs by kind, and for a RepSpec by whether it is assigned: an assigned
document is frozen (#83), so the only fix is a clone.
"""

from dataclasses import dataclass

from src.core.tools.audit_stored_documents import Finding, error_text

_LABELS = {
    "source_spec": "Source spec",
    "watch_spec": "Watch spec",
    "rep_fields": "Rep Fields",
    "rep_spec": "RepSpec document",
    "domain_watch_spec": "Domain cadence",
    "notification_content": "Notification content options",
}

_PATHS = {
    "source_spec": "/dashboard/info-sources/{}",
    "watch_spec": "/dashboard/info-items/{}",
    "rep_fields": "/dashboard/info-items/{}",
    "rep_spec": "/dashboard/rep-specs/{}",
    # The finding names the Domain by its ULID; its page is keyed by hostname.
    "domain_watch_spec": "/dashboard/domains/",
    "notification_content": "/dashboard/notifications/{}/edit",
}

_REMEDIES = {
    "source_spec": "Edit the Source Specification and fix or remove the flagged keys.",
    "watch_spec": "Set the cadence again: the Watcher panel writes a fresh document.",
    "rep_fields": "Edit the Rep Fields and fix or remove the flagged keys.",
    "rep_spec": "Edit the document - it is still a draft.",
    "domain_watch_spec": "Set the domain's default cadence again on its Fetch policy row.",
    "notification_content": (
        "Save the subscription's form again: it rewrites the content options. A Jinja "
        "template that fails is fixed through the API (archiver#363)."
    ),
}
"""Every kind in ``audit_stored_documents.KINDS`` needs a label, a page and a
remedy: ``finding_view`` indexes all three (guard test in test_registry_audit)."""

_FROZEN_REMEDY = (
    "Assigned, so the document is frozen (#83) and cannot gain new assignments. "
    "Clone it with a valid document and move the assignments."
)


@dataclass(frozen=True, slots=True)
class FindingView:
    """One finding as the list page and the detail notices render it."""

    label: str
    href: str
    row_id: str
    index: int | None
    messages: list[str]
    remedy: str


def finding_view(finding: Finding) -> FindingView:
    """Name ``finding`` for an operator: its kind, its page, its errors, its remedy."""
    return FindingView(
        label=_LABELS[finding.kind],
        href=_PATHS[finding.kind].format(finding.row_id),
        row_id=finding.row_id,
        index=finding.index,
        messages=[error_text(e) for e in finding.errors],
        remedy=_FROZEN_REMEDY if finding.frozen else _REMEDIES[finding.kind],
    )


def finding_views(findings: list[Finding]) -> list[FindingView]:
    """``finding_view`` over a list, in the order given."""
    return [finding_view(f) for f in findings]
