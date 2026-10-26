"""WatchSpec validation against the v1 JSON Schema.

The document is **cadence only**. Active/paused lives on the sibling column
``info_items.watch_active`` and rides the announcement envelope beside
``revoked`` — co-core's ``RegistryAnnouncementState`` types it there. Nothing
downstream would catch the mistake if it drifted back in here: ``watch_spec`` is
an untyped ``dict`` on the wire, so a nested ``active: false`` validates cleanly
while the envelope reports "no opinion yet" and the consumer keeps scheduling a
paused item. This module's schema is the only thing that rejects it.

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

DEFAULT_WATCH_SPEC: dict = {"schema_version": 1}
"""The cadence policy applied when nobody has expressed one.

Deliberately carries no ``interval``: a default here would fabricate a cadence
for every item that has none, overriding what it inherits - its host's default
cadence, else Watcher's own (archiver#364). Registration writes an explicit
interval when the operator picks one; everything else inherits.

Carries no ``active`` either — pause state is the sibling column
``info_items.watch_active``, whose ``NULL`` means "not yet imported from
Watcher". See ``v1.json``'s description for why the two are separate.
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


def validate_domain_watch_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Validate a Domain's default cadence (archiver#360). Returns (ok, errors).

    A WatchSpec v1 document that also **carries ``interval``**: without one it
    says nothing a ``NULL`` does not, and cadence resolution (#364) takes the
    domain tier only when there is an interval to take. The API, the dashboard,
    the Watcher import and the stored-document sweep all judge by this.
    """
    ok, errors = validate_watch_spec(doc)
    if ok and "interval" not in doc:
        errors = [
            {
                "path": "/interval",
                "message": "a domain default needs an interval; NULL is no default",
            }
        ]
    return (len(errors) == 0, errors)
