from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.capture_wait_policy_kind import CaptureWaitPolicyKind
from ..types import UNSET, Unset

T = TypeVar("T", bound="CaptureWaitPolicy")


@_attrs_define
class CaptureWaitPolicy:
    """What the page must reach, after ``load``, before it is captured.

    Attributes:
        kind (CaptureWaitPolicyKind):
        seconds (float | int | None | Unset):
        selector (None | str | Unset):
    """

    kind: CaptureWaitPolicyKind
    seconds: float | int | None | Unset = UNSET
    selector: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value

        seconds: float | int | None | Unset
        if isinstance(self.seconds, Unset):
            seconds = UNSET
        else:
            seconds = self.seconds

        selector: None | str | Unset
        if isinstance(self.selector, Unset):
            selector = UNSET
        else:
            selector = self.selector

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
            }
        )
        if seconds is not UNSET:
            field_dict["seconds"] = seconds
        if selector is not UNSET:
            field_dict["selector"] = selector

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        kind = CaptureWaitPolicyKind(d.pop("kind"))

        def _parse_seconds(data: object) -> float | int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | int | None | Unset, data)

        seconds = _parse_seconds(d.pop("seconds", UNSET))

        def _parse_selector(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        selector = _parse_selector(d.pop("selector", UNSET))

        capture_wait_policy = cls(
            kind=kind,
            seconds=seconds,
            selector=selector,
        )

        return capture_wait_policy
