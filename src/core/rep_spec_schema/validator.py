"""RepSpec validation: envelope, alias name, per-provider object_options sub-schema, template.

The alias rule is co-core's (``co_core.pure.util.aliases``), shared with
Replicator, which refuses a non-conforming binding when it loads its alias
table. Checking it here makes a bad name fail when the RepSpec is saved rather
than as ``alias_unknown`` on the first replication (archiver#276). Only the
write paths and the ``validate-rep-spec`` dry run call this, so an assigned
RepSpec whose document is frozen (#83) is never re-judged by a rule added after
it froze.

The template checks live in ``src.core.replication.template`` rather than here
because the *renderer* enforces the same rules from the same parser
(archiver#168) — a document that validates has to be one that renders, and
``document`` freezes on assignment (#83), so the two drifting apart produces a
RepSpec nobody can fix.
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from co_core.pure.util.aliases import REPLICATION_PROVIDERS, alias_provider
from jsonschema import Draft202012Validator

from src.core.replication.template import validate_path_template

ENVELOPE_PATH = Path(__file__).resolve().parent / "v1.json"
PROVIDERS_DIR = Path(__file__).resolve().parent / "providers"

# The one pre-rule name, and the provider it was bound under. Production's single
# RepSpec carries it; Replicator accepts it outside the rule until 2026-12-31
# (replicator#114) and binds it beside ``gcs-publication`` through the
# publication cutover. Removed once the data migration moves that RepSpec off it.
LEGACY_ALIASES: dict[str, str] = {"primary": "gcs"}
# Replicator's date for ``primary``: after it, every boot logs an ERROR and its CI
# fails. A test here fails from the same day while LEGACY_ALIASES is non-empty.
LEGACY_ALIASES_DEADLINE = date(2026, 12, 31)


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

    errors.extend(_alias_errors(doc, envelope_errors=errors))

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


def _alias_errors(doc: dict, *, envelope_errors: list[ValidationError]) -> list[ValidationError]:
    """Check ``credentials_alias`` against the shared name rule and ``provider``.

    Skipped when the envelope already refused the alias (absent, empty, not a
    string), so one fault reports once. The prefix check needs a known provider:
    comparing against ``'ftp'``, or against ``None`` when the field is missing
    (whose error sits at ``/``, not ``/provider``), would describe a mismatch with
    a value that is itself the error.
    """
    alias = doc.get("credentials_alias")
    if not isinstance(alias, str) or any(
        e["path"] == "/credentials_alias" for e in envelope_errors
    ):
        return []
    provider = doc.get("provider")

    if alias in LEGACY_ALIASES:
        named = LEGACY_ALIASES[alias]
    else:
        try:
            named = alias_provider(alias)
        except ValueError as e:
            return [{"path": "/credentials_alias", "message": str(e)}]

    if provider in REPLICATION_PROVIDERS and named != provider:
        return [
            {
                "path": "/credentials_alias",
                "message": (
                    f"credentials_alias {alias!r} names provider {named!r}, "
                    f"but the RepSpec's provider is {provider!r}."
                ),
            }
        ]
    return []
