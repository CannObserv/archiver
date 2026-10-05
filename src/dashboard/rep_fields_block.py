"""The Replication section's Fields block: what each row shows, and the form it posts.

One row per **raw** key the operator types, gathered from the ``required_fields``
of the specs the block covers (archiver#307). A spec requires ``org.title_slug``;
the operator enters ``org.title``, and the row shows the slug it derives. Every
value on a row comes from the effective bag (``effective_rep_fields``), the same
resolution render and the gate read, so a row cannot say "stored" for a value
the gate would refuse.

Pure: the route loads the bag, the specs and the org. Kept out of the route
module the way ``watch_panel.py`` is, so the badge rules have unit tests that
need no database.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from src.core.rep_fields import OrgValues, effective_rep_fields, empty_slug_reason

_SLUG = "_slug"
_COMPOSITES = ("acronym_or_title", "acronym_or_title_slug")
# A leading all-caps token before a spaced dash: "WSLCB - Meeting Schedule".
_ACRONYM_PREFIX = re.compile(r"^[A-Z][A-Z0-9]+ - (?P<rest>.+)$")


class StoredField(NamedTuple):
    """A key and its stored value, as the form round-trips it."""

    key: str
    value: object

    @property
    def input_type(self) -> str:
        """``string`` posts verbatim; ``json`` parses it if it can, keeping 2024 a number."""
        return "string" if isinstance(self.value, str) or self.value is None else "json"

    @property
    def input_value(self) -> str:
        """The value as the input holds it."""
        if self.value is None:
            return ""
        return self.value if isinstance(self.value, str) else json.dumps(self.value)

    @property
    def dom_id(self) -> str:
        """An id-safe form of the key: v1 keys never hold ``-``, so ``.`` maps to it."""
        return self.key.replace(".", "-")


class Readout(NamedTuple):
    """A required key derived from the row's raw value, and what the effective bag holds."""

    key: str
    value: object


@dataclass(frozen=True, slots=True)
class FieldRow:
    """One raw key some spec needs, and where its value comes from.

    ``badge`` is the source: ``stored``, ``override`` (a stored ``_slug`` stands
    in for the derivation; its input, in ``overrides``, sits on the first row
    it feeds only), ``from_power_map`` (the linked org supplies it,
    archiver#304), ``slugs_to_nothing`` (``reason`` says which value, worded by
    the gate, archiver#312) or ``missing``.
    """

    key: str
    value: object
    required_by: tuple[str, ...]
    readouts: tuple[Readout, ...]
    overrides: tuple[StoredField, ...]
    badge: str
    reason: str | None
    suggestion: str | None

    @property
    def stored(self) -> StoredField:
        """The row's own value in the shape the form round-trips."""
        return StoredField(self.key, self.value)


@dataclass(frozen=True, slots=True)
class FieldsView:
    """Everything the block renders from the bag."""

    rows: tuple[FieldRow, ...]
    other_fields: tuple[StoredField, ...]


class FieldsFormError(ValueError):
    """The posted rows cannot be built into a bag; the message names the row."""


def suggest_item_name(name: str, acronym: str | None) -> str | None:
    """The item name without its leading ``"<acronym> - "``, or ``None`` if it has none.

    The bag's acronym when there is one; otherwise a leading all-caps token,
    which is how item names are written ("WSLCB - Meeting Schedule").
    """
    if acronym and name.startswith(f"{acronym} - "):
        rest = name.removeprefix(f"{acronym} - ").strip()
        return rest or None
    match = _ACRONYM_PREFIX.match(name)
    return match.group("rest").strip() or None if match else None


def _raw_keys(key: str) -> list[str]:
    """The keys in the same namespace the operator types for one required key."""
    if key in _COMPOSITES:
        return ["acronym", "title"]
    if key.endswith(_SLUG) and key != _SLUG:
        return [key.removesuffix(_SLUG)]
    return [key]


def build_fields(
    bag: dict,
    specs: Sequence[tuple[str, Mapping[str, object]]],
    *,
    org: OrgValues | None,
    item_name: str,
) -> FieldsView:
    """The block's rows and other fields for ``bag`` against ``specs`` (name, document).

    Badges are computed per row from the effective bag, so a value that slugs
    to nothing shows as such even while another row is still missing - the
    gate reports missing keys first and would hide it (archiver#312).
    """
    resolved = effective_rep_fields(bag, org)
    # raw key -> (spec names, derived required keys), in first-seen order
    feeds: dict[str, tuple[list[str], list[str]]] = {}
    for spec_name, document in specs:
        for required in document.get("required_fields") or []:
            ns, _, key = str(required).partition(".")
            if not ns or not key:
                continue
            for raw in _raw_keys(key):
                names, derived = feeds.setdefault(f"{ns}.{raw}", ([], []))
                if spec_name not in names:
                    names.append(spec_name)
                if key != raw and required not in derived:
                    derived.append(required)

    # A stored derived key gets one input, on the first row it feeds: the
    # composite feeds two, and posting its key twice is refused (CR 1).
    placed: set[str] = set()
    rows = tuple(
        _row(full, names, derived, bag, resolved, org, item_name, placed)
        for full, (names, derived) in feeds.items()
    )
    claimed = {r.key for r in rows} | {o.key for r in rows for o in r.overrides}
    other: list[StoredField] = []
    for ns, fields in bag.items():
        if not isinstance(fields, dict):
            other.append(StoredField(ns, fields))
            continue
        other += [
            StoredField(f"{ns}.{k}", v) for k, v in fields.items() if f"{ns}.{k}" not in claimed
        ]
    return FieldsView(rows=rows, other_fields=tuple(other))


def _row(
    full: str,
    required_by: list[str],
    derived: list[str],
    bag: dict,
    resolved: dict,
    org: OrgValues | None,
    item_name: str,
    placed: set[str],
) -> FieldRow:
    ns, _, key = full.partition(".")
    stored_ns = bag.get(ns) if isinstance(bag.get(ns), dict) else {}
    resolved_ns = resolved.get(ns) if isinstance(resolved.get(ns), dict) else {}
    readouts = tuple(Readout(d, resolved_ns.get(d.partition(".")[2])) for d in derived)
    stored_derived = [d for d in derived if d.partition(".")[2] in stored_ns]
    overrides = tuple(
        StoredField(d, stored_ns[d.partition(".")[2]]) for d in stored_derived if d not in placed
    )
    placed.update(stored_derived)
    value = stored_ns.get(key)
    reason = None
    if stored_derived:
        badge = "override"
    elif value is not None:
        # The composite blames whichever raw field it took; keep only this row's.
        reasons = (empty_slug_reason(resolved, ns, d.partition(".")[2]) for d in derived)
        reason = next((r for r in reasons if r and r.startswith(f"{full} ")), None)
        badge = "slugs_to_nothing" if reason else "stored"
    elif org is not None and key not in stored_ns and resolved_ns.get(key) is not None:
        badge, value = "from_power_map", resolved_ns[key]
    else:
        badge = "missing"

    suggestion = None
    if full == "info_item.name":
        org_ns = resolved.get("org") if isinstance(resolved.get("org"), dict) else {}
        acronym = org_ns.get("acronym")
        suggestion = suggest_item_name(item_name, acronym if isinstance(acronym, str) else None)
        if suggestion == value:
            suggestion = None
    return FieldRow(
        key=full,
        value=value,
        required_by=tuple(required_by),
        readouts=readouts,
        overrides=overrides,
        badge=badge,
        reason=reason,
        suggestion=suggestion,
    )


def parse_fields_form(
    keys: list[str], values: list[str], types: list[str], *, strict: bool = True
) -> dict:
    """Build the bag the Fields form posted: parallel ``field_key``/``field_value``/``field_type``.

    A blank value means "not set" and is left out, as is a wholly blank added
    row. Shape is the gate's to judge (``set_rep_fields``), so a flat key or a
    bad namespace name passes through and is refused there, in the gate's
    words; this refuses only what cannot be built into a dict at all.

    ``field_type=json`` parses the value if it parses and keeps the text if it
    does not, so a stored number stays a number and a retyped one is not refused.

    ``strict=False`` is the live readout's reading of half-typed input: a row it
    cannot use is skipped, a repeated key keeps its last value, and a missing
    ``field_type`` means text.
    """
    if strict and not len(keys) == len(values) == len(types):
        raise FieldsFormError("The form posted mismatched field lists; reload and try again.")
    types = list(types) + ["string"] * (len(keys) - len(types))
    bag: dict = {}
    seen: set[str] = set()
    for raw_key, raw_value, kind in zip(keys, values, types, strict=False):
        try:
            _add_field(bag, seen, raw_key.strip(), raw_value, kind, strict=strict)
        except FieldsFormError:
            if strict:
                raise
    return bag


def _add_field(bag: dict, seen: set[str], key: str, raw_value: str, kind: str, *, strict: bool):
    if not key:
        if raw_value.strip():
            raise FieldsFormError(f"A field has a value but no name: {raw_value!r}")
        return
    if not raw_value.strip():
        return
    if key in seen and strict:
        raise FieldsFormError(f"{key} appears twice; keep one.")
    seen.add(key)
    value: object = raw_value
    if kind == "json":
        # "Parse it if it parses": the marker is invisible to the operator, so
        # retyping 2024 as "circa 2024" is an edit, not an error (CR 2).
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
    ns, dot, sub = key.partition(".")
    if not dot:
        if isinstance(bag.get(key), dict):
            raise FieldsFormError(f"{key} is both a namespace and a field")
        bag[key] = value
        return
    if ns in bag and not isinstance(bag[ns], dict):
        raise FieldsFormError(f"{ns} is both a field and a namespace")
    bag.setdefault(ns, {})[sub] = value
