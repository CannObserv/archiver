from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyWatchedItemCreateSubmitWatchedItemsNewPost")


@_attrs_define
class BodyWatchedItemCreateSubmitWatchedItemsNewPost:
    """
    Attributes:
        url (str | Unset):  Default: ''.
        name (str | Unset):  Default: ''.
        description (str | Unset):  Default: ''.
        default_schedule_interval (str | Unset):  Default: ''.
        default_content_type (str | Unset):  Default: ''.
        default_tags (str | Unset):  Default: ''.
    """

    url: str | Unset = ""
    name: str | Unset = ""
    description: str | Unset = ""
    default_schedule_interval: str | Unset = ""
    default_content_type: str | Unset = ""
    default_tags: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        name = self.name

        description = self.description

        default_schedule_interval = self.default_schedule_interval

        default_content_type = self.default_content_type

        default_tags = self.default_tags

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if url is not UNSET:
            field_dict["url"] = url
        if name is not UNSET:
            field_dict["name"] = name
        if description is not UNSET:
            field_dict["description"] = description
        if default_schedule_interval is not UNSET:
            field_dict["default_schedule_interval"] = default_schedule_interval
        if default_content_type is not UNSET:
            field_dict["default_content_type"] = default_content_type
        if default_tags is not UNSET:
            field_dict["default_tags"] = default_tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url", UNSET)

        name = d.pop("name", UNSET)

        description = d.pop("description", UNSET)

        default_schedule_interval = d.pop("default_schedule_interval", UNSET)

        default_content_type = d.pop("default_content_type", UNSET)

        default_tags = d.pop("default_tags", UNSET)

        body_watched_item_create_submit_watched_items_new_post = cls(
            url=url,
            name=name,
            description=description,
            default_schedule_interval=default_schedule_interval,
            default_content_type=default_content_type,
            default_tags=default_tags,
        )

        body_watched_item_create_submit_watched_items_new_post.additional_properties = d
        return body_watched_item_create_submit_watched_items_new_post

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
