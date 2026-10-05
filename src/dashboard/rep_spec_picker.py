"""The Replication section's Add-a-spec picker: what each unassigned spec would need, and render.

One entry per RepSpec not actively assigned to the item (archiver#308). Readiness
is the rep_fields gate's own answer (``check_bag_against_spec``, the check
``assign_rep_spec`` refuses on), so *Ready* here is the assign that succeeds and
*Can't render* carries the gate's words verbatim (archiver#312). The path is
rendered through ``render_destination`` against the occasion the route hands in:
the item's latest revision, or ``example_occasion()`` when it has none.

Pure: the route loads the bag, the specs, the revision and the org. Kept out of
the route module the way ``rep_fields_block.py`` is, so readiness has unit tests
that need no database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from src.core.models import RepSpec
from src.core.rep_fields import OrgValues
from src.core.rep_fields_schema.validator import validate_rep_fields
from src.core.replication.destination import RenderOccasion, render_destination
from src.core.replication.errors import ReplicationRenderError
from src.core.tools.rep_fields_gate import check_bag_against_spec
from src.dashboard.providers import UNWRITABLE_PROVIDERS
from src.dashboard.rep_fields_block import raw_keys

# The stand-in revision for an item that has captured nothing yet: all zeros, so
# the preview reads as an example and never as a citable id.
EXAMPLE_REVISION_ID = "0" * 26
_EXAMPLE_FINGERPRINT = "sha256:" + "0" * 64
_EXAMPLE_MEDIA_TYPE = "text/html"


@dataclass(frozen=True, slots=True)
class PickerEntry:
    """One unassigned spec, as the picker lists it.

    ``readiness`` is ``ready``, ``needs`` (``needs`` lists the raw keys to
    enter), ``unrenderable`` (``reason`` is the gate's) or ``unwritable``
    (``reason`` says which writer Replicator lacks, archiver#202). ``path`` is
    the rendered destination when ready; ``template`` is shown when it is not.
    """

    rep_spec_id: str
    name: str
    provider: str
    readiness: str
    needs: tuple[str, ...]
    reason: str | None
    path: str | None
    template: str | None

    @property
    def ready(self) -> bool:
        """Whether Assign is offered: the server re-checks either way."""
        return self.readiness == "ready"


def example_occasion() -> RenderOccasion:
    """A labelled stand-in occasion for an item with no revision: zeros, now, HTML."""
    return RenderOccasion(
        source_revision_id=EXAMPLE_REVISION_ID,
        content_fingerprint=_EXAMPLE_FINGERPRINT,
        captured_at=datetime.now(UTC),
        source_media_type=_EXAMPLE_MEDIA_TYPE,
    )


def build_picker(
    bag: dict,
    specs: Sequence[RepSpec],
    *,
    occasion: RenderOccasion,
    org: OrgValues | None,
) -> tuple[PickerEntry, ...]:
    """An entry per spec in ``specs``, in the order given."""
    return tuple(_entry(bag, spec, occasion, org) for spec in specs)


def _entry(
    bag: dict, spec: RepSpec, occasion: RenderOccasion, org: OrgValues | None
) -> PickerEntry:
    document = spec.document or {}
    template = document.get("path_template")
    template = template if isinstance(template, str) else None

    def entry(readiness: str, **kw) -> PickerEntry:
        return PickerEntry(
            rep_spec_id=str(spec.rep_spec_id),
            name=spec.name,
            provider=spec.provider,
            readiness=readiness,
            template=template,
            **{"needs": (), "reason": None, "path": None, **kw},
        )

    if spec.provider in UNWRITABLE_PROVIDERS:
        return entry("unwritable", reason=UNWRITABLE_PROVIDERS[spec.provider])
    # The gate files shape errors under ``missing``; as *Needs* a pre-#302
    # flat key would read as a key to add, when it is one to fix (CR 3).
    _, shape_errors = validate_rep_fields(bag)
    if shape_errors:
        problems = "; ".join(f"{e['path'].strip('/') or '/'}: {e['message']}" for e in shape_errors)
        return entry("unrenderable", reason=f"Rep Fields are off the v1 shape: {problems}")
    check = check_bag_against_spec(bag, document, org=org)
    if check.missing:
        needs = dict.fromkeys(_needs_label(m["path"]) for m in check.missing)
        return entry("needs", needs=tuple(needs))
    if check.unrenderable is not None:
        return entry("unrenderable", reason=check.unrenderable)
    if template is None:
        return entry("ready")
    try:
        path = render_destination(template, rep_fields=bag, occasion=occasion, org=org)
    except ReplicationRenderError as e:
        # The gate probes a placeholder occasion; the real one can still fail.
        return entry("unrenderable", reason=str(e))
    return entry("ready", path=path)


def _needs_label(path: str) -> str:
    """The key(s) the operator types for a missing required key: ``org.title`` for its slug."""
    ns, _, key = path.strip("/").replace("/", ".").partition(".")
    if not key:
        return ns
    return " or ".join(f"{ns}.{raw}" for raw in raw_keys(key))
