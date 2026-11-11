from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.capture_policy import CapturePolicy


T = TypeVar("T", bound="InfoSourceCapturePolicyPatch")


@_attrs_define
class InfoSourceCapturePolicyPatch:
    """Request body for PATCH /info-sources/{id}/capture-policy.

    Attributes:
        capture_policy (CapturePolicy | None): The replacement policy, replaced whole; omitted keys take their defaults.
            null clears it. Each viewport side 1..4096; a delay wait at most 30 s.
    """

    capture_policy: CapturePolicy | None

    def to_dict(self) -> dict[str, Any]:
        from ..models.capture_policy import CapturePolicy

        capture_policy: dict[str, Any] | None
        if isinstance(self.capture_policy, CapturePolicy):
            capture_policy = self.capture_policy.to_dict()
        else:
            capture_policy = self.capture_policy

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "capture_policy": capture_policy,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.capture_policy import CapturePolicy

        d = dict(src_dict)

        def _parse_capture_policy(data: object) -> CapturePolicy | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                capture_policy_type_0 = CapturePolicy.from_dict(data)

                return capture_policy_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CapturePolicy | None, data)

        capture_policy = _parse_capture_policy(d.pop("capture_policy"))

        info_source_capture_policy_patch = cls(
            capture_policy=capture_policy,
        )

        return info_source_capture_policy_patch
