from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyWatchedItemFieldUpdateWatchedItemsWatchedItemIdFieldFieldNamePost")


@_attrs_define
class BodyWatchedItemFieldUpdateWatchedItemsWatchedItemIdFieldFieldNamePost:
    """
    Attributes:
        value (str | Unset):  Default: ''.
    """

    value: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        value = d.pop("value", UNSET)

        body_watched_item_field_update_watched_items_watched_item_id_field_field_name_post = cls(
            value=value,
        )

        body_watched_item_field_update_watched_items_watched_item_id_field_field_name_post.additional_properties = d
        return body_watched_item_field_update_watched_items_watched_item_id_field_field_name_post

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
