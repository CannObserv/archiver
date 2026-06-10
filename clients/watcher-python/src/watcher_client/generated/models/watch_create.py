from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.content_type import ContentType
from ..types import UNSET, Unset

T = TypeVar("T", bound="WatchCreate")


@_attrs_define
class WatchCreate:
    """Schema for creating a new Watch.

    The WatchedItem must already exist. No Archiver SDK calls — URL resolution
    is the WatchedItem's responsibility (#185 Phase A).

        Attributes:
            name (str):
            watched_item_id (str):
            content_type (ContentType | None | Unset):
            description (None | str | Unset):
            tags (list[str] | None | Unset):
    """

    name: str
    watched_item_id: str
    content_type: ContentType | None | Unset = UNSET
    description: None | str | Unset = UNSET
    tags: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        watched_item_id = self.watched_item_id

        content_type: None | str | Unset
        if isinstance(self.content_type, Unset):
            content_type = UNSET
        elif isinstance(self.content_type, ContentType):
            content_type = self.content_type.value
        else:
            content_type = self.content_type

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "watched_item_id": watched_item_id,
            }
        )
        if content_type is not UNSET:
            field_dict["content_type"] = content_type
        if description is not UNSET:
            field_dict["description"] = description
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        watched_item_id = d.pop("watched_item_id")

        def _parse_content_type(data: object) -> ContentType | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                content_type_type_0 = ContentType(data)

                return content_type_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContentType | None | Unset, data)

        content_type = _parse_content_type(d.pop("content_type", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_tags(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tags_type_0 = cast(list[str], data)

                return tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tags = _parse_tags(d.pop("tags", UNSET))

        watch_create = cls(
            name=name,
            watched_item_id=watched_item_id,
            content_type=content_type,
            description=description,
            tags=tags,
        )

        watch_create.additional_properties = d
        return watch_create

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
