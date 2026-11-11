from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.capture_viewport_policy import CaptureViewportPolicy
    from ..models.capture_wait_policy import CaptureWaitPolicy


T = TypeVar("T", bound="CapturePolicy")


@_attrs_define
class CapturePolicy:
    """A source's capture settings, and whether each new revision triggers one.

    Attributes:
        full_page (bool | Unset):  Default: True.
        on_revision (bool | Unset):  Default: False.
        viewport (CaptureViewportPolicy | Unset): The browser viewport, in CSS pixels.
        wait (CaptureWaitPolicy | None | Unset):
    """

    full_page: bool | Unset = True
    on_revision: bool | Unset = False
    viewport: CaptureViewportPolicy | Unset = UNSET
    wait: CaptureWaitPolicy | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.capture_wait_policy import CaptureWaitPolicy

        full_page = self.full_page

        on_revision = self.on_revision

        viewport: dict[str, Any] | Unset = UNSET
        if not isinstance(self.viewport, Unset):
            viewport = self.viewport.to_dict()

        wait: dict[str, Any] | None | Unset
        if isinstance(self.wait, Unset):
            wait = UNSET
        elif isinstance(self.wait, CaptureWaitPolicy):
            wait = self.wait.to_dict()
        else:
            wait = self.wait

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if full_page is not UNSET:
            field_dict["full_page"] = full_page
        if on_revision is not UNSET:
            field_dict["on_revision"] = on_revision
        if viewport is not UNSET:
            field_dict["viewport"] = viewport
        if wait is not UNSET:
            field_dict["wait"] = wait

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capture_viewport_policy import CaptureViewportPolicy
        from ..models.capture_wait_policy import CaptureWaitPolicy

        d = dict(src_dict)
        full_page = d.pop("full_page", UNSET)

        on_revision = d.pop("on_revision", UNSET)

        _viewport = d.pop("viewport", UNSET)
        viewport: CaptureViewportPolicy | Unset
        if isinstance(_viewport, Unset):
            viewport = UNSET
        else:
            viewport = CaptureViewportPolicy.from_dict(_viewport)

        def _parse_wait(data: object) -> CaptureWaitPolicy | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                wait_type_0 = CaptureWaitPolicy.from_dict(data)

                return wait_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CaptureWaitPolicy | None | Unset, data)

        wait = _parse_wait(d.pop("wait", UNSET))

        capture_policy = cls(
            full_page=full_page,
            on_revision=on_revision,
            viewport=viewport,
            wait=wait,
        )

        return capture_policy
