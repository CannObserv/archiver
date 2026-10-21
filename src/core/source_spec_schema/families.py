"""Algorithm → content-kind family taxonomy.

Each extraction algorithm operates on a particular content kind. The Archiver
enforces that the specs in one ``source_specs`` list agree on the family,
because every spec in the list extracts from the same fetched bytes (the
"InfoSource URL = fetch group" invariant; see
``src/core/source_spec_schema/v1.json`` description). The check is per list,
not across an InfoItem's sources: an item has one primary (#392).

``css`` (HTML) and ``xpath`` (HTML and XML) select from markup (``html_text``);
``jsonpath`` from JSON (``json``, cannobserv#354, #356). ``full_page`` is family-neutral
(#356 D1): co-core honours it on every media type it dispatches, so it pairs
with either family. ``regex`` stays out, because co-core refuses it (#317).
"""

from collections.abc import Iterable
from typing import Literal

Family = Literal["html_text", "json"]

ALGORITHM_FAMILIES: dict[str, Family | None] = {
    "css": "html_text",
    "xpath": "html_text",
    "jsonpath": "json",
    "full_page": None,
}
"""``None`` marks a family-neutral algorithm: compatible with any family."""


class UnknownAlgorithmError(Exception):
    """Algorithm string is not classified in ALGORITHM_FAMILIES.

    Should never happen for documents that pass schema validation — guarded
    by tests/core/source_spec_schema/test_families.py.
    """


def family_for(algorithm: str) -> Family | None:
    """Return the content-kind family for ``algorithm``; ``None`` if it is family-neutral.

    Raises ``UnknownAlgorithmError`` if ``algorithm`` is not in the taxonomy.
    """
    try:
        return ALGORITHM_FAMILIES[algorithm]
    except KeyError as e:
        raise UnknownAlgorithmError(algorithm) from e


def families_of(algorithms: Iterable[str]) -> set[Family]:
    """The families ``algorithms`` commit a ``source_specs`` list to; more than one is a mix.

    Family-neutral algorithms commit to none. Raises ``UnknownAlgorithmError``
    as ``family_for`` does.
    """
    return {family for a in algorithms if (family := family_for(a)) is not None}
