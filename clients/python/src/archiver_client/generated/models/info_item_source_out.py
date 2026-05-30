from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

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
        role (None | str):
        deactivated_at (None | datetime.datetime): UTC timestamp when this binding was
            deactivated, or null if still active.
    """

    created_at: datetime.datetime
    info_source_id: str
    is_active: bool
    role: None | str
    deactivated_at: None | datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        info_source_id = self.info_source_id

        is_active = self.is_active

        role: None | str
        role = self.role

        deactivated_at: None | str
        if self.deactivated_at is None:
            deactivated_at = None
        else:
            deactivated_at = self.deactivated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "info_source_id": info_source_id,
                "is_active": is_active,
                "role": role,
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

        def _parse_role(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        role = _parse_role(d.pop("role"))

        def _parse_deactivated_at(data: object) -> None | datetime.datetime:
            if data is None:
                return data
            return isoparse(cast(str, data))

        deactivated_at = _parse_deactivated_at(d.pop("deactivated_at", None))

        info_item_source_out = cls(
            created_at=created_at,
            info_source_id=info_source_id,
            is_active=is_active,
            role=role,
            deactivated_at=deactivated_at,
        )

        info_item_source_out.additional_properties = d
        return info_item_source_out

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
