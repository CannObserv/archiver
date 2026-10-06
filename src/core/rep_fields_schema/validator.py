"""rep_fields validation — schema-shape check + required-field-presence check."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

from src.core.rep_fields import (
    ORG_NAMESPACE,
    ORG_OWNED_KEYS,
    OrgValues,
    effective_rep_fields,
    empty_slug_reason,
)

SCHEMA_PATH = Path(__file__).resolve().parent / "v1.json"


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def validate_rep_fields(bag: dict) -> tuple[bool, list[ValidationError]]:
    """Schema-validate the bag's namespacing convention only."""
    errors: list[ValidationError] = []
    for err in _validator().iter_errors(bag):
        errors.append(
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message,
            }
        )
    return (len(errors) == 0, errors)


def linked_org_key_errors(bag: dict) -> list[ValidationError]:
    """The stored ``org.title``/``org.acronym`` a linked item may not carry (archiver#304).

    While an item is linked to a Power Map org those two come from the org; a
    stored copy would silently shadow it. Other ``org`` keys stay overrides.
    The caller decides whether the item is linked.
    """
    stored = bag.get(ORG_NAMESPACE)
    if not isinstance(stored, dict):
        return []
    return [
        {
            "path": f"/{ORG_NAMESPACE}/{key}",
            "message": (
                f"{ORG_NAMESPACE}.{key} comes from the linked Power Map org; "
                "unlink the org to hand-type it"
            ),
        }
        for key in ORG_OWNED_KEYS
        if key in stored
    ]


def validate_rep_fields_against_spec(
    bag: dict, required_fields: list[str], *, org: OrgValues | None
) -> tuple[bool, list[ValidationError]]:
    """Run shape validation, then check that every '<ns>.<key>' in
    required_fields resolves to a non-null value in bag.

    Presence is checked on the *effective* bag (archiver#206, #303): a required
    ``org.title_slug`` is satisfied by a stored ``org.title`` or by ``org``'s
    name, because that is how ``render_destination`` will read it. Shape
    validation still runs on the bag as stored — the derived keys are strings
    and cannot fail it.

    A required ``_slug`` key whose raw value slugged to nothing still fails, but
    its message names the raw field (archiver#312).
    """
    _, errors = validate_rep_fields(bag)
    missing, empty_slugs = check_required_fields(bag, required_fields, org=org)
    errors += missing + empty_slugs
    return not errors, errors


def check_required_fields(
    bag: dict, required_fields: list[str], *, org: OrgValues | None
) -> tuple[list[ValidationError], list[ValidationError]]:
    """The presence half of ``validate_rep_fields_against_spec``, split by remedy.

    Returns ``(missing, empty_slugs)``. ``missing`` is a key the bag lacks (or a
    malformed entry), which the operator fixes by adding a value. ``empty_slugs``
    is a derived ``_slug`` key withheld because the raw value the operator *did*
    enter slugs to nothing (archiver#312): the remedy is a different value, which
    makes it a render failure rather than a gap, and the rep_fields gate reports
    it as one.
    """
    # A separate name, not a rebind: every error below reports a path, and a
    # reader has to be able to tell which bag it is a path into. Unconditional:
    # an `isinstance(bag, dict)` guard here bought nothing, because the loop
    # below calls `.get` either way — a list reached it and raised
    # AttributeError one line later, which is the failure the guard read as
    # prevented. The annotation is the contract (CR 12).
    resolved = effective_rep_fields(bag, org)
    missing: list[ValidationError] = []
    empty_slugs: list[ValidationError] = []
    for path in required_fields:
        ns, _, key = path.partition(".")
        if not ns or not key:
            missing.append(
                {
                    "path": f"/{path}",
                    "message": f"required_fields entry {path!r} is malformed (expect 'ns.key')",
                }
            )
            continue
        ns_dict = resolved.get(ns)
        if not isinstance(ns_dict, dict) or key not in ns_dict or ns_dict.get(key) is None:
            reason = empty_slug_reason(resolved, ns, key)
            if reason is not None:
                empty_slugs.append({"path": f"/{ns}/{key}", "message": reason})
            else:
                missing.append(
                    {"path": f"/{ns}/{key}", "message": f"required field {path} missing or null"}
                )
    return missing, empty_slugs
