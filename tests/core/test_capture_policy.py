"""A source's capture policy: shape, bounds, and the command values it resolves to (#380 C)."""

import math

import pytest
from co_core.pure.models.changes import (
    CaptureViewportEmit,
    ContentCaptureCommandEmit,
    DelayWaitEmit,
    NetworkIdleWaitEmit,
    SelectorWaitEmit,
)
from pydantic import ValidationError

from src.core.capture_policy import (
    DEFAULT_POLICY,
    MAX_DELAY_SECONDS,
    MAX_VIEWPORT_SIDE,
    CapturePolicy,
    effective_policy,
    validate_capture_policy,
)


def test_default_policy_is_slice_a_profile_and_opts_out_of_revisions():
    assert DEFAULT_POLICY.viewport.width == 1280
    assert DEFAULT_POLICY.viewport.height == 800
    assert DEFAULT_POLICY.full_page is True
    assert DEFAULT_POLICY.wait is None
    assert DEFAULT_POLICY.on_revision is False


def test_empty_document_takes_every_default():
    assert CapturePolicy.model_validate({}) == DEFAULT_POLICY


def test_effective_policy_falls_back_to_the_default_for_none():
    assert effective_policy(None) == DEFAULT_POLICY


def test_effective_policy_reads_a_stored_document():
    stored = {"viewport": {"width": 390, "height": 844}, "full_page": False, "on_revision": True}
    policy = effective_policy(stored)
    assert (policy.viewport.width, policy.viewport.height) == (390, 844)
    assert policy.full_page is False
    assert policy.on_revision is True


@pytest.mark.parametrize("side", [0, -1, MAX_VIEWPORT_SIDE + 1])
@pytest.mark.parametrize("axis", ["width", "height"])
def test_viewport_side_outside_replicators_range_is_refused(axis, side):
    viewport = {"width": 1280, "height": 800, axis: side}
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate({"viewport": viewport})


def test_viewport_bounds_are_inclusive():
    policy = CapturePolicy.model_validate({"viewport": {"width": 1, "height": MAX_VIEWPORT_SIDE}})
    assert policy.viewport.height == MAX_VIEWPORT_SIDE


@pytest.mark.parametrize(
    "document",
    [
        {"viewport": {"width": "1280", "height": 800}},
        {"viewport": {"width": 1280.5, "height": 800}},
        {"full_page": "yes"},
        {"on_revision": 1},
    ],
)
def test_types_are_strict(document):
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate(document)


@pytest.mark.parametrize(
    "document",
    [
        {"surprise": 1},
        {"viewport": {"width": 1, "height": 1, "scale": 2}},
        {"wait": {"kind": "networkidle", "timeout": 5}},
    ],
)
def test_unknown_keys_are_refused_at_every_level(document):
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate(document)


def test_unknown_wait_kind_is_refused():
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate({"wait": {"kind": "load"}})


@pytest.mark.parametrize(
    "wait",
    [
        {"kind": "networkidle"},
        {"kind": "selector", "selector": "main article"},
        {"kind": "delay", "seconds": 2.5},
        {"kind": "delay", "seconds": MAX_DELAY_SECONDS},
        {"kind": "delay", "seconds": 3},
    ],
)
def test_valid_waits_are_kept(wait):
    policy = CapturePolicy.model_validate({"wait": wait})
    assert policy.wait is not None
    assert policy.wait.kind == wait["kind"]


@pytest.mark.parametrize(
    "wait",
    [
        {"kind": "selector"},
        {"kind": "selector", "selector": "   "},
        {"kind": "selector", "selector": "a", "seconds": 1},
        {"kind": "networkidle", "selector": "a"},
        {"kind": "networkidle", "seconds": 1},
        {"kind": "delay"},
        {"kind": "delay", "seconds": 0},
        {"kind": "delay", "seconds": -1},
        {"kind": "delay", "seconds": MAX_DELAY_SECONDS + 0.001},
        {"kind": "delay", "seconds": math.inf},
        {"kind": "delay", "seconds": math.nan},
        {"kind": "delay", "seconds": 1, "selector": "a"},
    ],
)
def test_invalid_waits_are_refused(wait):
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate({"wait": wait})


def test_selector_is_bounded():
    with pytest.raises(ValidationError):
        CapturePolicy.model_validate({"wait": {"kind": "selector", "selector": "a" * 1025}})


@pytest.mark.parametrize(
    ("wait", "emit_type"),
    [
        (None, type(None)),
        ({"kind": "networkidle"}, NetworkIdleWaitEmit),
        ({"kind": "selector", "selector": "#main"}, SelectorWaitEmit),
        ({"kind": "delay", "seconds": 4}, DelayWaitEmit),
    ],
)
def test_every_valid_policy_resolves_to_a_sendable_command(wait, emit_type):
    policy = CapturePolicy.model_validate({"viewport": {"width": 800, "height": 600}, "wait": wait})
    viewport = policy.viewport_emit()
    resolved = policy.wait_emit()
    assert isinstance(viewport, CaptureViewportEmit)
    assert (viewport.width, viewport.height) == (800, 600)
    assert isinstance(resolved, emit_type)
    # The co-core producer model accepts the pair: nothing we store is unsendable.
    ContentCaptureCommandEmit(
        occurred_at="2026-11-11T00:00:00Z",
        command_id="01M75H603VX307CE6YRMTJV3NR",
        url="https://example.org/",
        info_source_id="01KTCNXKXN7Z94G495YEGM6JX3",
        viewport=viewport,
        full_page=policy.full_page,
        wait=resolved,
    )


def test_stored_form_round_trips():
    policy = CapturePolicy.model_validate(
        {"wait": {"kind": "selector", "selector": "#x"}, "on_revision": True}
    )
    stored = policy.model_dump(mode="json")
    assert CapturePolicy.model_validate(stored) == policy
    assert stored["wait"] == {"kind": "selector", "selector": "#x", "seconds": None}


def test_validate_capture_policy_reports_in_the_sweeps_shape():
    ok, errors = validate_capture_policy({"viewport": {"width": 0, "height": 800}})
    assert ok is False
    assert errors and errors[0]["path"] == "/viewport/width"
    assert validate_capture_policy({"on_revision": True}) == (True, [])


def test_validate_capture_policy_refuses_a_non_object():
    ok, errors = validate_capture_policy(["not", "an", "object"])
    assert ok is False
    assert errors
