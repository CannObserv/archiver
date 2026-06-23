from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyWatchedItemToggleActiveWatchedItemsWatchedItemIdToggleActivePost")


@_attrs_define
class BodyWatchedItemToggleActiveWatchedItemsWatchedItemIdToggleActivePost:
    """
    Attributes:
        active (str | Unset):  Default: ''.
        toggle_id (str | Unset):  Default: 'watched-item-status-toggle'.
        compact (str | Unset):  Default: ''.
    """

    active: str | Unset = ""
    toggle_id: str | Unset = "watched-item-status-toggle"
    compact: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        active = self.active

        toggle_id = self.toggle_id

        compact = self.compact

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if active is not UNSET:
            field_dict["active"] = active
        if toggle_id is not UNSET:
            field_dict["toggle_id"] = toggle_id
        if compact is not UNSET:
            field_dict["compact"] = compact

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        active = d.pop("active", UNSET)

        toggle_id = d.pop("toggle_id", UNSET)

        compact = d.pop("compact", UNSET)

        body_watched_item_toggle_active_watched_items_watched_item_id_toggle_active_post = cls(
            active=active,
            toggle_id=toggle_id,
            compact=compact,
        )

        body_watched_item_toggle_active_watched_items_watched_item_id_toggle_active_post.additional_properties = d
        return body_watched_item_toggle_active_watched_items_watched_item_id_toggle_active_post

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
