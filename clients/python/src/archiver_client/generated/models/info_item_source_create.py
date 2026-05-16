from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.info_item_source_create_role_type_0 import InfoItemSourceCreateRoleType0
from ..types import UNSET, Unset

T = TypeVar("T", bound="InfoItemSourceCreate")


@_attrs_define
class InfoItemSourceCreate:
    """Request body for POST /info-items/{id}/info-sources.

    Attributes:
        info_source_id (str): ULID of an existing InfoSource.
        role (InfoItemSourceCreateRoleType0 | None | Unset): Binding role. ``null`` (default) for root-shaped
            InfoSources (the InfoItem's primary). ``'cross_check'`` or ``'sub_aspect'`` for fragment-shaped InfoSources
            sharing the primary's root.
    """

    info_source_id: str
    role: InfoItemSourceCreateRoleType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        info_source_id = self.info_source_id

        role: None | str | Unset
        if isinstance(self.role, Unset):
            role = UNSET
        elif isinstance(self.role, InfoItemSourceCreateRoleType0):
            role = self.role.value
        else:
            role = self.role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "info_source_id": info_source_id,
            }
        )
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        info_source_id = d.pop("info_source_id")

        def _parse_role(data: object) -> InfoItemSourceCreateRoleType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                role_type_0 = InfoItemSourceCreateRoleType0(data)

                return role_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InfoItemSourceCreateRoleType0 | None | Unset, data)

        role = _parse_role(d.pop("role", UNSET))

        info_item_source_create = cls(
            info_source_id=info_source_id,
            role=role,
        )

        info_item_source_create.additional_properties = d
        return info_item_source_create

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
