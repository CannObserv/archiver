"""``path_template`` parsing and the create/update-time contract (archiver#168).

One parser serves two callers — the RepSpec validation gate and the renderer —
so a template that validates is a template that renders. Two parsers would drift
silently, and the cost of drift here is not a loud failure: ``document`` is
frozen once a RepSpec is assigned (archiver#83), so a template that passes
validation and then fails to render is unfixable in place.

Three rules the envelope schema cannot express:

**The vocabulary is split, and only half is declarable.** ``required_fields``
covers the InfoItem's ``rep_fields`` bag. The other half — ``source_revision.*``
— is supplied per replication *occasion* and cannot live in a bag at all, so
listing it in ``required_fields`` demands something no InfoItem can hold. The
namespace is reserved in both directions: declared here, rejected there.

**Placeholders and ``required_fields`` must agree.** ``required_fields`` is
hand-maintained rather than derived, so a template naming ``{org.acronym_slug}``
while ``required_fields`` omits it validates, assigns, freezes — and then raises
at render time. Checking the two against each other at the gate is what keeps
that from reaching a frozen document.

**A rendered destination must be unique per occasion** (the issuer contract's
R2). A template discriminated only by ``{source_revision.date}`` renders one key
for two revisions captured the same day; the consumer reports that as
``destination_conflict``, which reads as a conflict rather than as the
path-design error it is. So the template must carry ``{source_revision.id}`` or
``{source_revision.fingerprint}``.
"""

from __future__ import annotations

import re
from typing import TypedDict

from src.core.replication.errors import ReplicationRenderError

# The namespace supplied by the replication occasion rather than by the
# InfoItem's rep_fields bag. Reserved: it may not appear in required_fields.
OCCASION_NAMESPACE = "source_revision"

# Closed vocabulary — exactly what src.core.replication.destination supplies.
# Adding a key here without teaching the renderer to resolve it would let a
# template validate and then fail to render, which is the drift this module's
# single-parser rule exists to prevent.
OCCASION_KEYS = frozenset({"id", "date", "fingerprint", "captured_at"})

# The subset that makes a rendered path distinct per occasion (R2). ``date`` is
# deliberately absent — it is the collision case, not a discriminator.
DISCRIMINATOR_KEYS = frozenset({"id", "fingerprint"})

# ``{namespace.key}`` using the rep_fields naming rule (rep_fields_schema/v1.json)
# on both halves, so a placeholder is spelled exactly like a required_fields entry.
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\}")

# Any brace-delimited run, well-formed or not — what the malformedness check
# compares against, so a typo cannot pass as literal text.
_ANY_BRACED = re.compile(r"\{[^{}]*\}")


class ValidationError(TypedDict):
    """The shape both schema validators already return."""

    path: str
    message: str


class MalformedTemplateError(ReplicationRenderError, ValueError):
    """The template is not parseable — an unnamespaced or unbalanced placeholder.

    Raised by :func:`parse_placeholders` for callers that hold an already-valid
    document (the renderer). The create/update gate calls
    :func:`validate_path_template`, which reports it as an error instead.
    """


def parse_placeholders(template: str) -> list[tuple[str, str]]:
    """Return every ``{namespace.key}`` in ``template``, left to right.

    Duplicates are preserved: a template may legitimately use one value twice,
    and the callers that care about uniqueness dedupe themselves.

    Raises:
        MalformedTemplateError: a brace sits outside a well-formed ``{ns.key}``
            pair. Both spellings of that — a stray brace and a braced run that is
            not a namespaced key — are typos, and neither may reach a document
            that freezes on assignment.
    """
    braced = _ANY_BRACED.findall(template)
    bad = [run for run in braced if not _PLACEHOLDER.fullmatch(run)]
    if bad:
        raise MalformedTemplateError(
            f"path_template placeholders must be spelled '{{namespace.key}}': {bad!r}"
        )

    # Every brace must belong to one of those runs. Counting openers against
    # closers is not enough: a stray opener and a stray closer cancel, so
    # "}{info_item.slug}{" balances while carrying two braces into the rendered
    # path (CR #1). Removing the well-formed runs and looking for leftovers
    # states the rule directly instead.
    if "{" in _ANY_BRACED.sub("", template) or "}" in _ANY_BRACED.sub("", template):
        raise MalformedTemplateError(f"stray brace in path_template: {template!r}")

    return _PLACEHOLDER.findall(template)


def validate_path_template(template: str, *, required_fields: list[str]) -> list[ValidationError]:
    """Check one RepSpec document's template against ``required_fields``.

    Returns the (possibly empty) error list rather than raising, matching the
    envelope and provider validators it is called alongside.
    """
    errors: list[ValidationError] = []

    for entry in required_fields:
        namespace, _, _key = entry.partition(".")
        if namespace == OCCASION_NAMESPACE:
            errors.append(
                {
                    "path": "/required_fields",
                    "message": (
                        f"{entry!r} names the reserved {OCCASION_NAMESPACE!r} namespace, which is "
                        "supplied per replication occasion and cannot be held in rep_fields"
                    ),
                }
            )

    try:
        placeholders = parse_placeholders(template)
    except MalformedTemplateError as e:
        errors.append({"path": "/path_template", "message": str(e)})
        return errors

    declared = set(required_fields)
    for namespace, key in placeholders:
        if namespace == OCCASION_NAMESPACE:
            if key not in OCCASION_KEYS:
                errors.append(
                    {
                        "path": "/path_template",
                        "message": (
                            f"{namespace}.{key} is not a value the renderer supplies; "
                            f"the {OCCASION_NAMESPACE} namespace holds "
                            f"{sorted(OCCASION_KEYS)}"
                        ),
                    }
                )
            continue
        if f"{namespace}.{key}" not in declared:
            errors.append(
                {
                    "path": "/path_template",
                    "message": (
                        f"{namespace}.{key} is used by path_template but absent from "
                        "required_fields, so nothing guarantees the bag holds it"
                    ),
                }
            )

    if not any(
        namespace == OCCASION_NAMESPACE and key in DISCRIMINATOR_KEYS
        for namespace, key in placeholders
    ):
        errors.append(
            {
                "path": "/path_template",
                "message": (
                    "path_template needs a per-occasion discriminator — one of "
                    + ", ".join(f"{{{OCCASION_NAMESPACE}.{k}}}" for k in sorted(DISCRIMINATOR_KEYS))
                    + " — so two revisions cannot render the same destination"
                ),
            }
        )

    return errors
