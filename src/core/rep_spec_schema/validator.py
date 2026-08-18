"""RepSpec validation: envelope, per-provider object_options sub-schema, template.

The template checks live in ``src.core.replication.template`` rather than here
because the *renderer* enforces the same rules from the same parser
(archiver#168) — a document that validates has to be one that renders, and
``document`` freezes on assignment (#83), so the two drifting apart produces a
RepSpec nobody can fix.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

from src.core.replication.template import validate_path_template

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

    # Run whenever the two fields the template rules read are themselves sound.
    # Suppressing on *any* envelope error would cost an author a round trip —
    # fix the alias, resubmit, learn the template is wrong too (CR #8) — while
    # reporting "no discriminator" about an absent path_template would describe
    # a document nobody wrote. Hence the narrow gate: the fields' own errors, not
    # the document's.
    template = doc.get("path_template")
    required_fields = doc.get("required_fields")
    template_field_errors = [
        e for e in errors if e["path"] in ("/path_template", "/required_fields")
    ]
    if (
        not template_field_errors
        and isinstance(template, str)
        and isinstance(required_fields, list)
    ):
        errors.extend(validate_path_template(template, required_fields=required_fields))

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
