"""resolve_rep_fields — domain bag normalization for InfoItem.rep_fields."""

import re

_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with `_`, trim leading/trailing `_`."""
    s = _SLUG_NON_WORD.sub("_", value.lower()).strip("_")
    return re.sub(r"_+", "_", s)


def resolve_rep_fields(bag: dict) -> dict:
    """Enrich a raw bag with `_slug` companions for string fields and acronym/title derivations.

    - For each namespace, every string field gets a `<key>_slug` companion.
    - If a namespace contains both `acronym` and `title`, derive `acronym_or_title`
      and `acronym_or_title_slug` (preferring acronym when present).
    - Idempotent: existing `_slug` keys are preserved (never overwritten).
    - Unknown namespaces and non-string values are passed through unchanged.
    """
    out: dict = {}
    for ns, fields in bag.items():
        if isinstance(fields, dict):
            ns_out = dict(fields)
            for key, val in list(fields.items()):
                if isinstance(val, str) and not key.endswith("_slug"):
                    slug_key = f"{key}_slug"
                    ns_out.setdefault(slug_key, slugify(val))
            if "acronym" in fields and "title" in fields:
                aot = fields.get("acronym") or fields.get("title")
                if isinstance(aot, str) and aot:
                    ns_out.setdefault("acronym_or_title", aot)
                    ns_out.setdefault("acronym_or_title_slug", slugify(aot))
            out[ns] = ns_out
        else:
            out[ns] = fields
    return out
