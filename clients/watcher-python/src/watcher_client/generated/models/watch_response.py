from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.content_type import ContentType
from ..types import UNSET, Unset

T = TypeVar("T", bound="WatchResponse")


@_attrs_define
class WatchResponse:
    """Schema for returning a Watch.

    Per-Watch fields: identity (id, watched_item_id), display
    (name, content_type, description, tags), lifecycle flags
    (is_active, is_archived, suspended_by_domain), timestamps
    (created_at, updated_at). Health and URL live on WatchedItem.

        Attributes:
            id (str):
            name (str):
            watched_item_id (str):
            is_active (bool):
            is_archived (bool):
            suspended_by_domain (bool):
            created_at (datetime.datetime):
            updated_at (datetime.datetime):
            content_type (ContentType | None | Unset):
            description (None | str | Unset):
            tags (list[str] | None | Unset):
    """

    id: str
    name: str
    watched_item_id: str
    is_active: bool
    is_archived: bool
    suspended_by_domain: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    content_type: ContentType | None | Unset = UNSET
    description: None | str | Unset = UNSET
    tags: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        watched_item_id = self.watched_item_id

        is_active = self.is_active

        is_archived = self.is_archived

        suspended_by_domain = self.suspended_by_domain

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

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
                "id": id,
                "name": name,
                "watched_item_id": watched_item_id,
                "is_active": is_active,
                "is_archived": is_archived,
                "suspended_by_domain": suspended_by_domain,
                "created_at": created_at,
                "updated_at": updated_at,
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
        id = d.pop("id")

        name = d.pop("name")

        watched_item_id = d.pop("watched_item_id")

        is_active = d.pop("is_active")

        is_archived = d.pop("is_archived")

        suspended_by_domain = d.pop("suspended_by_domain")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

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

        watch_response = cls(
            id=id,
            name=name,
            watched_item_id=watched_item_id,
            is_active=is_active,
            is_archived=is_archived,
            suspended_by_domain=suspended_by_domain,
            created_at=created_at,
            updated_at=updated_at,
            content_type=content_type,
            description=description,
            tags=tags,
        )

        watch_response.additional_properties = d
        return watch_response

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
