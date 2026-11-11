"""A source's capture policy: what a ``content.capture`` for it sends, and when (archiver#380 C).

Operator decision D2: the policy lives on the InfoSource (``info_sources.capture_policy``),
because a capture renders a URL and its settings are page-specific. D3: captures
on each new revision are **opt-in per source** (``on_revision``), on top of the
on-demand button; there is no schedule, because Watcher's cadence already drives
revisions.

A stored ``NULL`` means "no policy": on-demand captures use ``DEFAULT_POLICY``,
slice A's fixed profile, and no revision triggers one.

**Validated at write time against Replicator's limits**, so what we store is what
it will accept (``content-capture-issuer-contract.md``):

- each viewport side ``1..4096`` CSS pixels;
- ``wait`` is co-core's grammar: ``networkidle``, ``selector`` (a non-blank CSS
  selector) or ``delay`` (``seconds``, finite, over zero, at most
  ``MAX_DELAY_SECONDS``, Replicator's default ``REPLICATOR_CAPTURE_MAX_WAIT_SECONDS``).
  A selector the browser cannot parse still comes back ``invalid_request_options``:
  Archiver does not parse CSS.

An unknown key is refused at every level, and the types are strict, so a stored
document round-trips through ``model_dump(mode="json")`` unchanged.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from co_core.pure.models.changes import CaptureViewportEmit, CaptureWaitEmit
from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)

MAX_VIEWPORT_SIDE = 4096
"""Replicator refuses a side outside ``1..4096`` with ``invalid_request_options``."""

MAX_DELAY_SECONDS = 30.0
"""Replicator's default wait bound; a longer ``delay`` is refused up front."""

MAX_SELECTOR_LENGTH = 1024

WaitKind = Literal["networkidle", "selector", "delay"]

_WAIT_EMIT = TypeAdapter(CaptureWaitEmit)


class CaptureViewportPolicy(BaseModel):
    """The browser viewport, in CSS pixels."""

    model_config = {"extra": "forbid"}

    width: StrictInt = Field(default=1280, ge=1, le=MAX_VIEWPORT_SIDE)
    height: StrictInt = Field(default=800, ge=1, le=MAX_VIEWPORT_SIDE)


class CaptureWaitPolicy(BaseModel):
    """What the page must reach, after ``load``, before it is captured."""

    model_config = {"extra": "forbid"}

    kind: WaitKind
    selector: str | None = Field(default=None, max_length=MAX_SELECTOR_LENGTH)
    """``selector`` only: the CSS selector that must be visible."""
    seconds: StrictFloat | StrictInt | None = None
    """``delay`` only: how long to wait after ``load``."""

    @model_validator(mode="after")
    def _fields_match_kind(self) -> CaptureWaitPolicy:
        if self.kind == "selector":
            if self.selector is None or not self.selector.strip():
                raise ValueError("a selector wait needs a non-blank selector")
        elif self.selector is not None:
            raise ValueError(f"a {self.kind} wait takes no selector")
        if self.kind == "delay":
            if self.seconds is None:
                raise ValueError("a delay wait needs seconds")
            if not math.isfinite(self.seconds) or not 0 < self.seconds <= MAX_DELAY_SECONDS:
                raise ValueError(f"delay seconds must be over 0 and at most {MAX_DELAY_SECONDS:g}")
        elif self.seconds is not None:
            raise ValueError(f"a {self.kind} wait takes no seconds")
        return self


class CapturePolicy(BaseModel):
    """A source's capture settings, and whether each new revision triggers one."""

    model_config = {"extra": "forbid"}

    viewport: CaptureViewportPolicy = Field(default_factory=CaptureViewportPolicy)
    full_page: StrictBool = True
    """The whole document (up to 4096 x 32768 px), or only the viewport."""
    wait: CaptureWaitPolicy | None = None
    """``None``: capture once ``load`` fires."""
    on_revision: StrictBool = False
    """Capture each new revision of this source (D3's opt-in)."""

    def viewport_emit(self) -> CaptureViewportEmit:
        """The command's viewport, co-core's producer shape."""
        return CaptureViewportEmit(width=self.viewport.width, height=self.viewport.height)

    def wait_emit(self) -> Any:
        """The command's ``wait``, one of co-core's three variants, or ``None``."""
        if self.wait is None:
            return None
        return _WAIT_EMIT.validate_python(self.wait.model_dump(exclude_none=True))


DEFAULT_POLICY = CapturePolicy()
"""Slice A's profile: 1280 x 800, full page, no wait; never on a revision."""


def effective_policy(stored: dict[str, Any] | None) -> CapturePolicy:
    """The stored policy, or ``DEFAULT_POLICY`` where the source has none."""
    return DEFAULT_POLICY if stored is None else CapturePolicy.model_validate(stored)


def validate_capture_policy(document: Any) -> tuple[bool, list[dict[str, str]]]:
    """``(ok, errors)`` in the stored-document sweep's shape (``audit_stored_documents``)."""
    try:
        CapturePolicy.model_validate(document)
    except ValidationError as e:
        return False, [
            {"path": "/" + "/".join(str(part) for part in err["loc"]), "message": err["msg"]}
            for err in e.errors()
        ]
    return True, []
