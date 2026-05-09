"""SourceSpec validation against the v1 JSON Schema."""

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


def validate_root_source_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Validate a SourceSpec doc that must be a root (requires target.url)."""
    ok, errs = validate_source_spec(doc)
    if not doc.get("target", {}).get("url"):
        errs.append({"path": "/target/url", "message": "root source requires target.url"})
        ok = False
    return ok, errs


def validate_fragment_source_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Validate a SourceSpec doc that must be a fragment (must NOT carry target).

    Fragments inherit URL/fetch semantics from their parent InfoSource. Carrying
    a ``target`` block of their own would bypass the page-once cascade and
    create ambiguity about which URL is authoritative.
    """
    ok, errs = validate_source_spec(doc)
    if "target" in doc:
        errs.append({"path": "/target/url", "message": "fragment source must not carry target.url"})
        ok = False
    return ok, errs
