"""The Viewport Capture and Capture Policy cards' context (archiver#380).

Pure: the route reads the source's latest ``capture_commands`` row and its
``capture_policy``, and this turns them into what ``info_sources/_capture_card.html``
and ``info_sources/_capture_policy_card.html`` show, and the policy form back
into a ``CapturePolicy``. Metadata only: Archiver reads no stored bytes, so the
image itself waits on slice D.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from pydantic import ValidationError

from src.core.capture_policy import CapturePolicy, effective_policy
from src.core.models import CaptureCommand
from src.core.replication.permanent_store import permanent_blob_uri
from src.core.services.capture import MAX_CAPTURE_REISSUES, STATE_REQUESTED
from src.dashboard.watch_panel import format_age

#: How often the card re-reads itself while its command is open.
POLL_SECONDS = 5

#: Where a dead-lettered command lands - Replicator's, probed by broker.
DLQ = "content.capture.dlq"


class CaptureView(TypedDict):
    state: str
    open: bool
    sent: str
    revision_id: str | None
    attempt: int
    max_attempts: int
    requested_ago: str | None
    captured_ago: str | None
    reason: str | None
    detail: str | None
    status_code: int | None
    image_width: int | None
    image_height: int | None
    size_bytes: int | None
    content_fingerprint: str | None
    final_url: str | None
    blob_uri: str | None
    kept: bool
    expires_at: datetime | None
    expired: bool
    persisted_at: datetime | None
    horizon_minutes: int
    dlq: str


def capture_view(
    command: CaptureCommand | None, *, now: datetime, horizon: timedelta
) -> CaptureView | None:
    """``None`` for a source never captured; else the card's fields for ``command``."""
    if command is None:
        return None
    expires = command.blob_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return CaptureView(
        state=command.state,
        open=command.state == STATE_REQUESTED,
        sent=describe_profile(
            command.viewport_width, command.viewport_height, command.full_page, command.wait
        ),
        revision_id=str(command.source_revision_id) if command.source_revision_id else None,
        attempt=command.attempt,
        max_attempts=1 + MAX_CAPTURE_REISSUES,
        requested_ago=format_age(command.issued_at, now=now),
        captured_ago=format_age(command.captured_at, now=now),
        reason=command.reason,
        detail=command.detail,
        status_code=command.status_code,
        image_width=command.image_width,
        image_height=command.image_height,
        size_bytes=command.size_bytes,
        content_fingerprint=command.content_fingerprint,
        final_url=command.final_url,
        # Once kept, the temp URI goes with the temp store: show where the digest
        # lives in the permanent one (CR 13).
        blob_uri=_kept_uri(command) or command.blob_uri,
        kept=command.persisted_at is not None,
        expires_at=expires,
        expired=expires is not None and expires <= now,
        persisted_at=command.persisted_at,
        horizon_minutes=max(1, int(horizon.total_seconds() // 60)),
        dlq=DLQ,
    )


def _kept_uri(command: CaptureCommand) -> str | None:
    """The permanent store's URI once persisted; ``None`` before, or for a malformed digest."""
    if command.persisted_at is None or command.content_fingerprint is None:
        return None
    try:
        return permanent_blob_uri(command.content_fingerprint)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The policy: what it says, its form, and the form back into a policy (slice C)
# ---------------------------------------------------------------------------


def describe_wait(wait: Mapping[str, Any] | None) -> str:
    """When the page is captured, in the operator's words."""
    if not wait:
        return "after load"
    kind = wait.get("kind")
    if kind == "networkidle":
        return "once the network is idle"
    if kind == "selector":
        return f"once {wait.get('selector')} is visible"
    if kind == "delay":
        return f"{wait.get('seconds'):g} s after load"
    return f"after a {kind} wait"


def describe_profile(
    width: int, height: int, full_page: bool, wait: Mapping[str, Any] | None
) -> str:
    """``390×844, viewport only, once #main is visible``."""
    page = "full page" if full_page else "viewport only"
    return f"{width}×{height}, {page}, {describe_wait(wait)}"


class PolicyView(TypedDict):
    set: bool
    invalid: bool
    profile: str
    on_revision: bool


class PolicyForm(TypedDict):
    width: str
    height: str
    full_page: bool
    wait_kind: str
    wait_selector: str
    wait_seconds: str
    on_revision: bool


class PolicyFormError(ValueError):
    """The submitted form is not a policy; the message is the operator's to read."""


def policy_view(stored: dict | None) -> PolicyView:
    """The card's statement of the source's effective policy."""
    try:
        policy = effective_policy(stored)
    except ValidationError:
        return PolicyView(set=True, invalid=True, profile="", on_revision=False)
    return PolicyView(
        set=stored is not None,
        invalid=False,
        profile=_profile(policy),
        on_revision=policy.on_revision,
    )


def policy_form(stored: dict | None) -> PolicyForm:
    """The form's fields, prefilled from the effective policy (the default if unusable)."""
    try:
        policy = effective_policy(stored)
    except ValidationError:
        policy = effective_policy(None)
    wait = policy.wait
    return PolicyForm(
        width=str(policy.viewport.width),
        height=str(policy.viewport.height),
        full_page=policy.full_page,
        wait_kind=wait.kind if wait else "",
        wait_selector=(wait.selector or "") if wait else "",
        wait_seconds=f"{wait.seconds:g}" if wait and wait.seconds is not None else "",
        on_revision=policy.on_revision,
    )


def parse_policy_form(form: PolicyForm) -> CapturePolicy:
    """The submitted fields as a policy. Raises :class:`PolicyFormError`.

    Only the field the chosen wait kind uses is read, so a selector left over
    from switching kinds is not an error.
    """
    document: dict[str, Any] = {
        "viewport": {
            "width": _whole(form["width"], "width"),
            "height": _whole(form["height"], "height"),
        },
        "full_page": form["full_page"],
        "on_revision": form["on_revision"],
        "wait": _wait(form),
    }
    try:
        return CapturePolicy.model_validate(document)
    except ValidationError as e:
        raise PolicyFormError("; ".join(_error_line(err) for err in e.errors())) from e


def _wait(form: PolicyForm) -> dict[str, Any] | None:
    kind = form["wait_kind"]
    if kind == "":
        return None
    if kind == "selector":
        return {"kind": "selector", "selector": form["wait_selector"]}
    if kind == "delay":
        raw = form["wait_seconds"].strip()
        try:
            seconds = float(raw)
        except ValueError as e:
            raise PolicyFormError("delay seconds must be a number") from e
        return {"kind": "delay", "seconds": seconds}
    return {"kind": kind}


def _whole(raw: str, name: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as e:
        raise PolicyFormError(f"{name} must be a whole number of pixels") from e


def _error_line(err: Mapping[str, Any]) -> str:
    where = ".".join(str(part) for part in err["loc"] if not isinstance(part, int))
    message = str(err["msg"]).removeprefix("Value error, ")
    return f"{where}: {message}" if where else message


def _profile(policy: CapturePolicy) -> str:
    wait = policy.wait.model_dump() if policy.wait else None
    return describe_profile(policy.viewport.width, policy.viewport.height, policy.full_page, wait)
