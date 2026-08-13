from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="RepublishRegistryResponse")


@_attrs_define
class RepublishRegistryResponse:
    """Response body for POST /api/v1/tools/republish-registry-announcements.

    Attributes:
        triggered (bool): True — the snapshot loop was signalled; the publish itself happens asynchronously on the
            loop's task (202 semantics).
    """

    triggered: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        triggered = self.triggered

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "triggered": triggered,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        triggered = d.pop("triggered")

        republish_registry_response = cls(
            triggered=triggered,
        )

        republish_registry_response.additional_properties = d
        return republish_registry_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
