from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.content_type import ContentType
from ..types import UNSET, Unset

T = TypeVar("T", bound="WatchUpdate")


@_attrs_define
class WatchUpdate:
    """Schema for updating a Watch. All fields optional.

    Identity fields (info_item_id) are immutable after creation — re-target
    by deleting and recreating the Watch.

        Attributes:
            name (None | str | Unset):
            content_type (ContentType | None | Unset):
            is_active (bool | None | Unset):
            description (None | str | Unset):
            tags (list[str] | None | Unset):
    """

    name: None | str | Unset = UNSET
    content_type: ContentType | None | Unset = UNSET
    is_active: bool | None | Unset = UNSET
    description: None | str | Unset = UNSET
    tags: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        content_type: None | str | Unset
        if isinstance(self.content_type, Unset):
            content_type = UNSET
        elif isinstance(self.content_type, ContentType):
            content_type = self.content_type.value
        else:
            content_type = self.content_type

        is_active: bool | None | Unset
        if isinstance(self.is_active, Unset):
            is_active = UNSET
        else:
            is_active = self.is_active

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
        field_dict.update({})
        if name is not UNSET:
            field_dict["name"] = name
        if content_type is not UNSET:
            field_dict["content_type"] = content_type
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if description is not UNSET:
            field_dict["description"] = description
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

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

        def _parse_is_active(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_active = _parse_is_active(d.pop("is_active", UNSET))

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

        watch_update = cls(
            name=name,
            content_type=content_type,
            is_active=is_active,
            description=description,
            tags=tags,
        )

        watch_update.additional_properties = d
        return watch_update

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
