"""rep_fields normalization — the derived half of an InfoItem's domain bag.

**A leaf module, deliberately** (CR 2). It lived under ``src/core/tools/``, the
authoring layer routes call, and archiver#206 gave it two consumers in the
domain below that layer: ``src.core.replication.destination`` and
``src.core.rep_fields_schema.validator``. That made ``replication`` import
``tools`` while ``tools.assign_rep_spec`` imports ``replication`` — a cycle
held open only by ``src/core/tools/__init__.py`` happening to be empty, and one
no inline import could break, since ruff ``PLC0415`` bans those. Sited here it
imports nothing but co-core, so no consumer can be upstream of it.

The derived ``_slug`` companions are what ``path_template`` placeholders such as
``{org.title_slug}`` render from, and those segments sit beside directories the
CLI writes through the storage framework's ``*Vars``. One slugger cluster-wide
(archiver#206): co-core's ``normalize_string``, the function those ``*Vars``
call — "WSLCB - Meeting Schedule" is ``wslcb-meeting_schedule`` on both sides,
and diacritics fold instead of vanishing.

Consumed where the bag is read, never persisted, and only through
``effective_rep_fields`` (archiver#303): render, the ``required_fields`` check,
the probe, issuance, both tool routes and ``set_rep_fields`` all resolve there,
so operators enter raw values and a stored ``_slug`` key stays an explicit
override. A guard test (``tests/core/test_rep_fields_guard.py``) fails on any
other reference to ``resolve_rep_fields``.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from co_core.pure.util.text import normalize_string


@dataclass(frozen=True, slots=True)
class OrgValues:
    """The linked organization's identity, as the bag's ``org`` namespace reads it.

    ``name`` becomes ``org.title`` and ``acronym`` ``org.acronym``. Plain values,
    not a model: ``effective_rep_fields`` stays pure, and the caller decides
    where an org comes from (Power Map's local snapshot, archiver#304).
    """

    name: str
    acronym: str | None


def slugify(value: str) -> str:
    """The path-segment form of a display value: co-core's ``normalize_string``.

    Lower-cased, diacritics folded, runs of non-alphanumerics to ``_``, a
    spaced dash (``" - "``) kept as ``-``, leading and trailing separators
    trimmed. Delegated rather than reimplemented so it cannot drift from the
    storage framework's derivation.

    The case that surprises: an **unspaced** dash becomes ``_``, so ``wa-lcb``
    yields ``wa_lcb``. A value that already looks like a slug is still
    rewritten, and only the spaced form survives as a dash — which is why
    ``"WSLCB - Meeting Schedule"`` is ``wslcb-meeting_schedule`` and not
    ``wslcb_meeting_schedule``.
    """
    return normalize_string(value)


def resolve_rep_fields(bag: dict) -> dict:
    """Enrich a raw bag with `_slug` companions for string fields and acronym/title derivations.

    - For each namespace, every string field gets a `<key>_slug` companion,
      unless the derivation comes out empty (see the last bullet).
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


_SLUG_SUFFIX = "_slug"


def empty_slug_reason(resolved: Mapping[str, object], namespace: str, key: str) -> str | None:
    """Why ``<namespace>.<key>`` is absent, when the answer is "its raw value slugged to nothing".

    A derived ``_slug`` key the operator never typed is withheld when its raw
    value has no path-segment form (``resolve_rep_fields``' last bullet), and a
    message naming only the derived key points the operator at a key they never
    entered (archiver#312). This names the raw field and its value instead:
    ``org.title "!!!" slugs to nothing (org.title_slug)``. For
    ``acronym_or_title_slug`` the raw field is whichever of ``acronym`` and
    ``title`` the composite took.

    ``resolved`` is the **effective** bag. ``None`` for anything else: a key that
    is present (a stored null is a plain miss), not a ``_slug`` key, or whose raw
    value is absent, not a string, itself a ``_slug`` key, or slugs fine.
    """
    fields = resolved.get(namespace)
    if not isinstance(fields, Mapping) or key in fields or not key.endswith(_SLUG_SUFFIX):
        return None
    raw_key = key.removesuffix(_SLUG_SUFFIX)
    raw = fields.get(raw_key)
    # A `_slug` key never gets a companion of its own, so `<key>_slug_slug` is
    # absent whatever the value holds: a plain miss, not a value to blame.
    if not isinstance(raw, str) or raw_key.endswith(_SLUG_SUFFIX) or slugify(raw):
        return None
    if raw_key == "acronym_or_title":
        raw_key = next((k for k in ("acronym", "title") if fields.get(k) == raw), raw_key)
    shown = json.dumps(raw, ensure_ascii=False)
    return f"{namespace}.{raw_key} {shown} slugs to nothing ({namespace}.{key})"


def effective_rep_fields(bag: dict, org: OrgValues | None) -> dict:
    """The bag every consumer reads: the stored bag over the linked org, resolved.

    **The single resolution point** (archiver#303). Precedence, lowest first:
    the org's ``name``/``acronym`` as ``org.title``/``org.acronym`` (a ``None``
    acronym is skipped), then the stored bag key by key, then
    ``resolve_rep_fields``' derivations, which never replace a key already
    there. A stored non-dict ``org`` replaces the org's values whole; shape
    validation is what refuses it.

    Pure: the caller loads the org. With ``org=None`` the result is exactly
    ``resolve_rep_fields(bag)``. ``bag`` is never mutated.
    """
    if org is None:
        return resolve_rep_fields(bag)
    org_ns: dict = {"title": org.name}
    if org.acronym is not None:
        org_ns["acronym"] = org.acronym
    stored_org = bag.get("org", {})
    if isinstance(stored_org, dict):
        stored_org = {**org_ns, **stored_org}
    return resolve_rep_fields({**bag, "org": stored_org})
