"""rep_fields validation — schema-shape check + required-field-presence check."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

from src.core.tools.resolve_rep_fields import resolve_rep_fields

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


def validate_rep_fields_against_spec(
    bag: dict, required_fields: list[str]
) -> tuple[bool, list[ValidationError]]:
    """Run shape validation, then check that every '<ns>.<key>' in
    required_fields resolves to a non-null value in bag.

    Presence is checked on the *resolved* bag (archiver#206): a required
    ``org.title_slug`` is satisfied by a stored ``org.title``, because that is
    how ``render_destination`` will read it. Shape validation still runs on the
    bag as stored — the derived keys are strings and cannot fail it.
    """
    ok, errors = validate_rep_fields(bag)
    bag = resolve_rep_fields(bag) if isinstance(bag, dict) else bag
    for path in required_fields:
        ns, _, key = path.partition(".")
        if not ns or not key:
            errors.append(
                {
                    "path": f"/{path}",
                    "message": f"required_fields entry {path!r} is malformed (expect 'ns.key')",
                }
            )
            ok = False
            continue
        ns_dict = bag.get(ns)
        if not isinstance(ns_dict, dict) or key not in ns_dict or ns_dict.get(key) is None:
            errors.append(
                {
                    "path": f"/{ns}/{key}",
                    "message": f"required field {path} missing or null",
                }
            )
            ok = False
    return ok, errors
