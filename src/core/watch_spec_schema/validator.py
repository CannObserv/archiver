"""WatchSpec validation against the v1 JSON Schema."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "v1.json"

DEFAULT_WATCH_SPEC: dict = {"schema_version": 1, "active": True}
"""The policy applied when nobody has expressed one.

Deliberately carries no ``interval``: a resolved default here would fabricate a
cadence for every item that has none, overriding the consumer's own default
(which may be per-domain). Registration writes an explicit interval when the
operator picks one; everything else leaves the choice to the consumer.
"""


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def validate_watch_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Schema-validate a WatchSpec document. Returns (ok, errors)."""
    errors: list[ValidationError] = []
    for err in _validator().iter_errors(doc):
        errors.append(
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message,
            }
        )
    return (len(errors) == 0, errors)
