"""Render a ``content.replicate`` destination, or refuse to (archiver#168).

The issuer renders and the consumer receives strings (the ``content.replicate``
issuer contract's T3/R1). That places two obligations here that a downstream
service could not discharge:

**Refuse locally what the consumer would refuse remotely.** Replicator answers a
traversal segment, an absolute path or a container escape with a terminal
``invalid_destination`` fact — arriving asynchronously, on a service that cannot
fix the RepSpec. The same conditions are visible before the XADD, so they are
checked here and the command is never published.

**Refuse rather than rewrite.** A value carrying ``/`` or a space could be
slugified into something path-shaped, and the temptation is real because the bag
is author-entered free text. Two objections: the rendered path becomes a
*citable public URL*, so quietly altering it changes what the registry
publishes; and two distinct values that sanitize to one path render one
destination — which comes back as ``destination_conflict``, a token that reports
a conflict rather than the collapse that caused it. So the charset is narrow and
a value outside it is an error naming the field.

**The occasion namespace wins over the bag.** ``source_revision.*`` is supplied
per replication and a same-named bag namespace cannot shadow it — the reservation
in ``template.validate_path_template`` keeps such a bag from being *declarable*,
and this keeps it from mattering if one exists anyway.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote

from src.core.replication.errors import ReplicationRenderError
from src.core.replication.template import (
    OCCASION_NAMESPACE,
    MalformedTemplateError,
    parse_placeholders,
)

# A stand-in occasion for the assignment-time pre-flight: segment-safe by
# construction, so anything it fails on is the bag's or the template's doing.
_PROBE_OCCASION_ID = "0" * 26
_PROBE_FINGERPRINT = "sha256:" + "0" * 64

# What a rendered value may contain. Deliberately narrower than "safe": these are
# the characters that survive a GCS object name, a Drive file name and an
# archive.org identifier without encoding, quoting, or a provider-specific rule.
_SEGMENT_SAFE = re.compile(r"\A[A-Za-z0-9._-]+\Z")

# Segments no path may contain — traversal, the current directory, and the empty
# segment a doubled or trailing separator produces.
_REFUSED_SEGMENTS = frozenset({"", ".", ".."})

_DRIVE_QUALIFIER = re.compile(r"\A[A-Za-z]:")


class DestinationRenderError(ReplicationRenderError):
    """Base for every reason a destination could not be produced.

    One base so the issuance path (archiver#169) can record "unrenderable" as a
    single skip reason while still logging which of the five it was. It sits
    under ``ReplicationRenderError`` alongside ``MalformedTemplateError``, so a
    caller catches one class rather than two hierarchies (CR #4).
    """


class MissingFieldError(DestinationRenderError):
    """A placeholder names a bag value the InfoItem does not hold.

    ``required_fields`` is checked when a RepSpec is *assigned*, but
    ``rep_fields`` stays editable afterwards — so a template that was renderable
    at assignment can stop being renderable without anything failing loudly.
    """

    def __init__(self, namespace: str, key: str) -> None:
        self.field = f"{namespace}.{key}"
        super().__init__(f"rep_fields has no non-null value for {self.field}")


class InvalidFieldValueError(DestinationRenderError):
    """A bag value cannot be a path segment as written."""

    def __init__(self, namespace: str, key: str, value: object) -> None:
        self.field = f"{namespace}.{key}"
        self.value = value
        super().__init__(
            f"rep_fields value for {self.field} is not usable as a path segment: {value!r} "
            "(allowed: letters, digits, '.', '_', '-')"
        )


class InvalidOccasionError(DestinationRenderError):
    """An occasion value is not usable as a path segment.

    Separate from ``InvalidFieldValueError`` because the remedy differs: a bad
    bag value is an author's to fix, while a bad occasion value means the
    *caller* built ``RenderOccasion`` from something other than the revision row
    — a bug in the issuance path, not in the registry's content.
    """

    def __init__(self, key: str, value: object, reason: str) -> None:
        self.key = f"{OCCASION_NAMESPACE}.{key}"
        self.value = value
        super().__init__(f"occasion value {self.key} is unusable ({reason}): {value!r}")


class UnsafeDestinationError(DestinationRenderError):
    """The rendered path is one the consumer's guards would refuse."""

    def __init__(self, rendered: str, reason: str) -> None:
        self.rendered = rendered
        super().__init__(f"rendered destination refused ({reason}): {rendered!r}")


class DestinationCollisionError(DestinationRenderError):
    """Two assignments of one InfoItem rendered the same destination."""

    def __init__(self, destination: str, keys: list[str]) -> None:
        self.destination = destination
        self.keys = keys
        super().__init__(
            f"assignments {', '.join(keys)} render the same destination {destination!r}; "
            "one would land as destination_conflict rather than as the path-design error it is"
        )


@dataclass(frozen=True, slots=True)
class RenderOccasion:
    """The per-replication half of the template vocabulary.

    Named for the *occasion* rather than for the revision: a fresh ``command_id``
    and a fresh destination belong to one issuance, and a second replication of
    the same revision under the same assignment is a second occasion with the
    same values — which is exactly what makes a redelivery target the same key
    (T4's no-op row) while a genuinely new occasion does not.
    """

    source_revision_id: str
    content_fingerprint: str
    captured_at: datetime

    def values(self) -> dict[str, str]:
        """The ``source_revision.*`` vocabulary, rendered path-safe.

        ``fingerprint`` drops the ``sha256:`` prefix — the algorithm is fixed by
        ``src.core.fingerprints`` and a colon is not a character worth carrying
        into three providers' name rules. ``captured_at`` uses the *basic* ISO
        form for the same reason the prefix is dropped; the extended form the
        repo writes elsewhere carries colons.

        Every value is checked against the same segment charset the bag half
        pays (CR #2): the occasion is caller-supplied too, and a guard covering
        half its inputs is half a guard.

        Raises:
            InvalidOccasionError: ``captured_at`` is naive, or a value cannot be
                a path segment.
        """
        if self.captured_at.tzinfo is None:
            # astimezone() would read a naive value as VM-local and then stamp
            # 'Z' on the converted result — a wrong timestamp asserted as UTC,
            # inside a path that is permanent and citable (CR #3). The registry's
            # own column is timezone-aware, so this only ever fires on a caller
            # that built the occasion from something else.
            raise InvalidOccasionError("captured_at", self.captured_at, "naive datetime")

        captured = self.captured_at.astimezone(UTC)
        _, _, digest = self.content_fingerprint.rpartition(":")
        values = {
            "id": self.source_revision_id,
            "date": captured.date().isoformat(),
            "fingerprint": digest,
            "captured_at": captured.strftime("%Y%m%dT%H%M%SZ"),
        }
        for key, value in values.items():
            if not _SEGMENT_SAFE.match(value) or value in _REFUSED_SEGMENTS:
                raise InvalidOccasionError(
                    key, value, "not usable as a path segment (allowed: A-Za-z0-9._-)"
                )
        return values


def render_destination(
    template: str, *, rep_fields: Mapping[str, object], occasion: RenderOccasion
) -> str:
    """Resolve ``template`` into the provider-relative path the command carries.

    Raises:
        MalformedTemplateError: the template is not parseable. Unreachable for a
            document that passed ``validate_path_template``, which is why this
            is not folded into ``DestinationRenderError`` — it means the gate was
            bypassed, not that this replication cannot proceed.
        MissingFieldError: a bag value is absent or null.
        InvalidFieldValueError: a bag value is not usable as a path segment.
        UnsafeDestinationError: the rendered path would be refused downstream.
    """
    occasion_values = occasion.values()
    rendered = template
    for namespace, key in parse_placeholders(template):
        if namespace == OCCASION_NAMESPACE:
            value = occasion_values.get(key)
            if value is None:
                raise MalformedTemplateError(
                    f"{OCCASION_NAMESPACE}.{key} is not a value the renderer supplies"
                )
        else:
            value = _bag_value(rep_fields, namespace, key)
        rendered = rendered.replace(f"{{{namespace}.{key}}}", value)

    _assert_safe(rendered)
    return rendered


def probe_destination(document: Mapping[str, object], rep_fields: Mapping[str, object]) -> None:
    """Check that this document + bag could render, before the assignment exists.

    ``assign_rep_spec`` validates that every ``required_fields`` entry is present
    and non-null, which is a weaker statement than "renders": a value of
    ``"WA LCB"`` satisfies presence and then fails every replication under that
    spec (CR #5). Assignment is the last *synchronous* moment where an author can
    fix it — afterwards ``document`` is frozen (#83) and the failure arrives as a
    bus fact on a service that cannot repair it, which is the outcome the whole
    issuer-renders decision exists to avoid.

    A document with no ``path_template`` is a no-op: document validity is the
    create/update gate's job, and reporting it here would blame the assignment
    for a document that was already incomplete.

    Raises:
        ReplicationRenderError: the pair cannot produce a destination.
    """
    template = document.get("path_template")
    if not isinstance(template, str):
        return
    render_destination(
        template,
        rep_fields=rep_fields,
        occasion=RenderOccasion(
            source_revision_id=_PROBE_OCCASION_ID,
            content_fingerprint=_PROBE_FINGERPRINT,
            captured_at=datetime.now(UTC),
        ),
    )


def find_collisions(rendered: Mapping[str, str]) -> dict[str, list[str]]:
    """Group a fan-out set by destination, keeping only the shared ones.

    Keyed by whatever identifies the assignment to the caller (archiver#169
    passes ``info_item_rep_spec_id``). Returns ``{destination: [keys]}`` for
    every destination more than one key renders, empty when all are distinct.

    Non-raising because the issuance path decides *what to skip* from the
    answer: raising on the first group found would leave a second collision
    invisible, and skipping the whole set on account of one collision refuses
    assignments that are perfectly fine (CR #11/#12).
    """
    by_destination: dict[str, list[str]] = {}
    for key, destination in rendered.items():
        by_destination.setdefault(destination, []).append(key)
    return {
        destination: sorted(keys) for destination, keys in by_destination.items() if len(keys) > 1
    }


def assert_distinct_destinations(rendered: Mapping[str, str]) -> None:
    """Refuse a fan-out set in which two assignments target one path.

    The raising form, for callers that want a hard stop rather than a set to
    triage.

    Raises:
        DestinationCollisionError: two or more keys share a destination.
    """
    collisions = find_collisions(rendered)
    for destination, keys in collisions.items():
        raise DestinationCollisionError(destination, keys)


def _bag_value(rep_fields: Mapping[str, object], namespace: str, key: str) -> str:
    """Resolve one ``rep_fields`` entry into a path segment."""
    namespace_bag = rep_fields.get(namespace)
    if not isinstance(namespace_bag, Mapping):
        raise MissingFieldError(namespace, key)
    if key not in namespace_bag or namespace_bag[key] is None:
        raise MissingFieldError(namespace, key)

    raw = namespace_bag[key]
    # bool before int: it *is* an int in Python, and "True" is a Python spelling
    # rather than a path one.
    if isinstance(raw, bool):
        value = "true" if raw else "false"
    elif isinstance(raw, int | float):
        value = str(raw)
    elif isinstance(raw, str):
        value = raw
    else:
        raise InvalidFieldValueError(namespace, key, raw)

    if not _SEGMENT_SAFE.match(value):
        raise InvalidFieldValueError(namespace, key, raw)
    if value in _REFUSED_SEGMENTS:
        raise InvalidFieldValueError(namespace, key, raw)
    return value


def _assert_safe(rendered: str) -> None:
    """Apply the consumer's path guards to the rendered string.

    Checked on the rendered value and again on its percent-decoded form, per the
    issuer contract's T3: ``%2e%2e`` is a traversal a provider may normalize even
    though the literal string carries no ``..``.
    """
    for candidate in _decodings(rendered):
        _assert_safe_form(rendered, candidate)


def _decodings(rendered: str) -> list[str]:
    decoded = unquote(rendered)
    return [rendered] if decoded == rendered else [rendered, decoded]


def _assert_safe_form(rendered: str, candidate: str) -> None:
    if not candidate:
        raise UnsafeDestinationError(rendered, "empty")
    if candidate.startswith("/"):
        raise UnsafeDestinationError(rendered, "absolute path")
    if candidate.endswith("/"):
        raise UnsafeDestinationError(rendered, "trailing separator")
    if "\\" in candidate:
        raise UnsafeDestinationError(rendered, "backslash")
    if _DRIVE_QUALIFIER.match(candidate):
        raise UnsafeDestinationError(rendered, "drive qualifier")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
        raise UnsafeDestinationError(rendered, "control character")
    for segment in candidate.split("/"):
        if segment in _REFUSED_SEGMENTS:
            raise UnsafeDestinationError(rendered, f"segment {segment!r}")
        if segment != segment.strip():
            raise UnsafeDestinationError(rendered, "untrimmed segment")
