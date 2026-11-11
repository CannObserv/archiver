from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="CaptureViewportPolicy")


@_attrs_define
class CaptureViewportPolicy:
    """The browser viewport, in CSS pixels.

    Attributes:
        height (int | Unset):  Default: 800.
        width (int | Unset):  Default: 1280.
    """

    height: int | Unset = 800
    width: int | Unset = 1280

    def to_dict(self) -> dict[str, Any]:
        height = self.height

        width = self.width

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if height is not UNSET:
            field_dict["height"] = height
        if width is not UNSET:
            field_dict["width"] = width

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        height = d.pop("height", UNSET)

        width = d.pop("width", UNSET)

        capture_viewport_policy = cls(
            height=height,
            width=width,
        )

        return capture_viewport_policy
