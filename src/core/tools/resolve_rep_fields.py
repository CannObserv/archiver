"""resolve_rep_fields — domain bag normalization for InfoItem.rep_fields.

The derived ``_slug`` companions are what ``path_template`` placeholders such as
``{org.title_slug}`` render from, and those segments sit beside directories the
CLI writes through the storage framework's ``*Vars``. One slugger cluster-wide
(archiver#206): co-core's ``normalize_string``, the function those ``*Vars``
call — "WSLCB - Meeting Schedule" is ``wslcb-meeting_schedule`` on both sides,
and diacritics fold instead of vanishing.

Consumed where the bag is read, never persisted: ``render_destination``,
``assign_rep_spec``'s ``required_fields`` check and ``POST /tools/validate-rep-fields``
all resolve the stored bag on the way in, so operators enter raw values and a
stored ``_slug`` key stays an explicit override.
"""

from co_core.pure.util.text import normalize_string


def slugify(value: str) -> str:
    """The path-segment form of a display value: co-core's ``normalize_string``.

    Lower-cased, diacritics folded, runs of non-alphanumerics to ``_``, a
    spaced dash (``" - "``) kept as ``-``, leading and trailing separators
    trimmed. Delegated rather than reimplemented so it cannot drift from the
    storage framework's derivation.
    """
    return normalize_string(value)


def resolve_rep_fields(bag: dict) -> dict:
    """Enrich a raw bag with `_slug` companions for string fields and acronym/title derivations.

    - For each namespace, every string field gets a `<key>_slug` companion.
    - If a namespace contains both `acronym` and `title`, derive `acronym_or_title`
      and `acronym_or_title_slug` (preferring acronym when present).
    - Idempotent: existing `_slug` keys are preserved (never overwritten).
    - Unknown namespaces and non-string values are passed through unchanged.
    - **A companion that would be empty is not written** (CR 1). The storage
      framework's rule is that a slug derivation yields `None` on empty raw
      input, never `""` (cannobserv docs/STORAGE_VARS.md S2), and the reason is
      exactly what a present-but-empty key costs here: it satisfies the
      presence check in `validate_rep_fields_against_spec` for a value that can
      never be a path segment, so an unusable bag validates and then fails at
      render time. Absent is the honest answer, and it is the one the caller
      can act on.
    """
    out: dict = {}
    for ns, fields in bag.items():
        if isinstance(fields, dict):
            ns_out = dict(fields)
            for key, val in list(fields.items()):
                if isinstance(val, str) and not key.endswith("_slug"):
                    slug = slugify(val)
                    if slug:
                        ns_out.setdefault(f"{key}_slug", slug)
            if "acronym" in fields and "title" in fields:
                aot = fields.get("acronym") or fields.get("title")
                if isinstance(aot, str) and aot:
                    ns_out.setdefault("acronym_or_title", aot)
                    # The raw composite stands on its own; only the derived half
                    # is withheld when it would be empty.
                    aot_slug = slugify(aot)
                    if aot_slug:
                        ns_out.setdefault("acronym_or_title_slug", aot_slug)
            out[ns] = ns_out
        else:
            out[ns] = fields
    return out
