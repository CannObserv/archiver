from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.info_item_out import InfoItemOut


T = TypeVar("T", bound="PageInfoItemOut")


@_attrs_define
class PageInfoItemOut:
    """
    Attributes:
        has_more (bool):
        items (list[InfoItemOut]):
        limit (int):
        offset (int):
    """

    has_more: bool
    items: list[InfoItemOut]
    limit: int
    offset: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        has_more = self.has_more

        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        limit = self.limit

        offset = self.offset

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "has_more": has_more,
                "items": items,
                "limit": limit,
                "offset": offset,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_item_out import InfoItemOut

        d = dict(src_dict)
        has_more = d.pop("has_more")

        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = InfoItemOut.from_dict(items_item_data)

            items.append(items_item)

        limit = d.pop("limit")

        offset = d.pop("offset")

        page_info_item_out = cls(
            has_more=has_more,
            items=items,
            limit=limit,
            offset=offset,
        )

        page_info_item_out.additional_properties = d
        return page_info_item_out

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
