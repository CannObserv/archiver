from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyWatchCreateSubmitWatchesNewPost")


@_attrs_define
class BodyWatchCreateSubmitWatchesNewPost:
    """
    Attributes:
        name (str | Unset):  Default: ''.
        watched_item_id (str | Unset):  Default: ''.
        content_type (str | Unset):  Default: 'html'.
        description (str | Unset):  Default: ''.
    """

    name: str | Unset = ""
    watched_item_id: str | Unset = ""
    content_type: str | Unset = "html"
    description: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        watched_item_id = self.watched_item_id

        content_type = self.content_type

        description = self.description

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if name is not UNSET:
            field_dict["name"] = name
        if watched_item_id is not UNSET:
            field_dict["watched_item_id"] = watched_item_id
        if content_type is not UNSET:
            field_dict["content_type"] = content_type
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name", UNSET)

        watched_item_id = d.pop("watched_item_id", UNSET)

        content_type = d.pop("content_type", UNSET)

        description = d.pop("description", UNSET)

        body_watch_create_submit_watches_new_post = cls(
            name=name,
            watched_item_id=watched_item_id,
            content_type=content_type,
            description=description,
        )

        body_watch_create_submit_watches_new_post.additional_properties = d
        return body_watch_create_submit_watches_new_post

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
