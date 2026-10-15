"""SourceSpec validation against the v1 JSON Schema.

Tightening this schema (archiver#164): stored documents are validated on write
only, so the PR ships a data migration or the stored-document sweep's "0 affected"
(docs/CONVENTIONS.md § Schema tightenings).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "v1.json"


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def validate_source_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Schema-validate a SourceSpec document. Returns (ok, errors)."""
    errors: list[ValidationError] = []
    for err in _validator().iter_errors(doc):
        errors.append(
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message,
            }
        )
    return (len(errors) == 0, errors)
