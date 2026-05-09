"""RepSpec validation: envelope + per-provider object_options sub-schema."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

ENVELOPE_PATH = Path(__file__).resolve().parent / "v1.json"
PROVIDERS_DIR = Path(__file__).resolve().parent / "providers"


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _envelope() -> Draft202012Validator:
    return Draft202012Validator(json.loads(ENVELOPE_PATH.read_text()))


@lru_cache
def _provider_validator(provider: str) -> Draft202012Validator | None:
    candidate = PROVIDERS_DIR / provider / "v1.json"
    if not candidate.is_file():
        return None
    return Draft202012Validator(json.loads(candidate.read_text()))


def validate_rep_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Validate a RepSpec document against the envelope and provider sub-schema.

    Returns a (ok, errors) tuple where ok is True iff the document is valid,
    and errors is a list of ValidationError dicts with path and message keys.
    """
    errors: list[ValidationError] = []
    for err in _envelope().iter_errors(doc):
        errors.append(
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message,
            }
        )

    provider = doc.get("provider")
    if provider:
        sub = _provider_validator(provider)
        if sub is None:
            errors.append(
                {
                    "path": "/provider",
                    "message": f"unknown provider: {provider!r}",
                }
            )
        else:
            for err in sub.iter_errors(doc.get("object_options", {})):
                errors.append(
                    {
                        "path": "/object_options/" + "/".join(str(p) for p in err.absolute_path),
                        "message": err.message,
                    }
                )

    return (len(errors) == 0, errors)
