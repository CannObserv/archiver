"""The content-fingerprint spelling — one pattern, three callers.

``sha256:<64 lowercase hex>`` is a domain rule, not an HTTP one. The API schema
validates request bodies against it, and the ``content.revisions`` consumer
validates wire values against it because co-core types ``extracted_fingerprint``
as a bare ``str`` and there is no Pydantic layer on that path.

It lives here rather than in ``src.core.services.source_revision`` so importing
the rule does not drag the ORM, SQLAlchemy, and co-core into a module that only
needs a regex (CR round 1, finding 10).

``is_valid_fingerprint`` is the whole public surface. The pattern stays an
implementation detail so a third caller cannot reach for the regex and rebuild
the check a shade differently (CR round 2, finding 19).
"""

from __future__ import annotations

import re

# Matched with ``fullmatch``, not ``match`` + ``$``. Python's ``$`` also matches
# immediately *before* a trailing newline, so the anchored-looking
# ``^sha256:[0-9a-f]{64}$`` accepted "sha256:<hex>\n" — which is a second
# spelling of one digest, and therefore a second row under the uniqueness key
# rather than a rejected write. Caught by this module's mirror test the first
# time the rule was tested directly (CR round 2, finding 19).
_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def is_valid_fingerprint(value: str) -> bool:
    """Whether ``value`` is spelled ``sha256:<64 lowercase hex>``, exactly."""
    return bool(_FINGERPRINT_PATTERN.fullmatch(value))
