from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="InfoItemSourceOut")


@_attrs_define
class InfoItemSourceOut:
    """Light projection of an info_item_sources row.

    Attributes:
        created_at (datetime.datetime):
        info_source_id (str):
        is_active (bool): True when deactivated_at is null (binding is currently active).
        deactivated_at (None | datetime.datetime): UTC timestamp when this binding was
            deactivated, or null if still active.
    """

    created_at: datetime.datetime
    info_source_id: str
    is_active: bool
    deactivated_at: None | datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()
        info_source_id = self.info_source_id
        is_active = self.is_active
        deactivated_at: None | str = (
            None if self.deactivated_at is None else self.deactivated_at.isoformat()
        )

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "info_source_id": info_source_id,
                "is_active": is_active,
                "deactivated_at": deactivated_at,
            }
        )
        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))
        info_source_id = d.pop("info_source_id")
        is_active = d.pop("is_active")

        _deactivated_at = d.pop("deactivated_at", None)
        deactivated_at: None | datetime.datetime = (
            None if _deactivated_at is None else isoparse(_deactivated_at)
        )

        obj = cls(
            created_at=created_at,
            info_source_id=info_source_id,
            is_active=is_active,
            deactivated_at=deactivated_at,
        )
        obj.additional_properties = d
        return obj

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
