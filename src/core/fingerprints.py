"""The content-fingerprint spelling — one pattern, three callers.

``sha256:<64 lowercase hex>`` is a domain rule, not an HTTP one. The API schema
validates request bodies against it, and the ``content.revisions`` consumer
validates wire values against it because co-core types ``extracted_fingerprint``
as a bare ``str`` and there is no Pydantic layer on that path.

It lives here rather than in ``src.core.services.source_revision`` so importing
the rule does not drag the ORM, SQLAlchemy, and co-core into a module that only
needs a regex (CR round 1, finding 10).
"""

from __future__ import annotations

import re

FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_valid_fingerprint(value: str) -> bool:
    """Whether ``value`` is spelled ``sha256:<64 lowercase hex>``."""
    return bool(FINGERPRINT_PATTERN.match(value))
