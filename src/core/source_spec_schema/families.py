"""Algorithm → content-kind family taxonomy.

Each extraction algorithm operates on a particular content kind. The Archiver
enforces that all InfoSources bound to a single InfoItem agree on the family,
because every fragment's extraction runs against the InfoItem's primary's
fetched bytes (the "InfoItem = fetch group" invariant; see
``src/core/source_spec_schema/v1.json`` description).
"""

from typing import Literal

Family = Literal["html_text", "json"]

ALGORITHM_FAMILIES: dict[str, Family] = {
    "css": "html_text",
    "xpath": "html_text",
    "regex": "html_text",
    "full_page": "html_text",
    "jsonpath": "json",
}


class UnknownAlgorithmError(Exception):
    """Algorithm string is not classified in ALGORITHM_FAMILIES.

    Should never happen for documents that pass schema validation — guarded
    by tests/core/source_spec_schema/test_families.py.
    """


def family_for(algorithm: str) -> Family:
    """Return the content-kind family for ``algorithm``.

    Raises ``UnknownAlgorithmError`` if ``algorithm`` is not in the taxonomy.
    """
    try:
        return ALGORITHM_FAMILIES[algorithm]
    except KeyError as e:
        raise UnknownAlgorithmError(algorithm) from e
