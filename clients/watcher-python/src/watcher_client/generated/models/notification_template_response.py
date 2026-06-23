from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config import ContentConfig


T = TypeVar("T", bound="NotificationTemplateResponse")


@_attrs_define
class NotificationTemplateResponse:
    """
    Attributes:
        id (str):
        title (str):
        channel_hint (str):
        events (list[str]):
        visibility (str):
        is_active (bool):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
        domain_name (None | str | Unset):
        watched_item_id (None | str | Unset):
        content_config (ContentConfig | None | Unset):
        remote_channel_id (None | str | Unset):
    """

    id: str
    title: str
    channel_hint: str
    events: list[str]
    visibility: str
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    domain_name: None | str | Unset = UNSET
    watched_item_id: None | str | Unset = UNSET
    content_config: ContentConfig | None | Unset = UNSET
    remote_channel_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.content_config import ContentConfig

        id = self.id

        title = self.title

        channel_hint = self.channel_hint

        events = self.events

        visibility = self.visibility

        is_active = self.is_active

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        domain_name: None | str | Unset
        if isinstance(self.domain_name, Unset):
            domain_name = UNSET
        else:
            domain_name = self.domain_name

        watched_item_id: None | str | Unset
        if isinstance(self.watched_item_id, Unset):
            watched_item_id = UNSET
        else:
            watched_item_id = self.watched_item_id

        content_config: dict[str, Any] | None | Unset
        if isinstance(self.content_config, Unset):
            content_config = UNSET
        elif isinstance(self.content_config, ContentConfig):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        remote_channel_id: None | str | Unset
        if isinstance(self.remote_channel_id, Unset):
            remote_channel_id = UNSET
        else:
            remote_channel_id = self.remote_channel_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "channel_hint": channel_hint,
                "events": events,
                "visibility": visibility,
                "is_active": is_active,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        if domain_name is not UNSET:
            field_dict["domain_name"] = domain_name
        if watched_item_id is not UNSET:
            field_dict["watched_item_id"] = watched_item_id
        if content_config is not UNSET:
            field_dict["content_config"] = content_config
        if remote_channel_id is not UNSET:
            field_dict["remote_channel_id"] = remote_channel_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config import ContentConfig

        d = dict(src_dict)
        id = d.pop("id")

        title = d.pop("title")

        channel_hint = d.pop("channel_hint")

        events = cast(list[str], d.pop("events"))

        visibility = d.pop("visibility")

        is_active = d.pop("is_active")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        def _parse_domain_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        domain_name = _parse_domain_name(d.pop("domain_name", UNSET))

        def _parse_watched_item_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        watched_item_id = _parse_watched_item_id(d.pop("watched_item_id", UNSET))

        def _parse_content_config(data: object) -> ContentConfig | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                content_config_type_0 = ContentConfig.from_dict(data)

                return content_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContentConfig | None | Unset, data)

        content_config = _parse_content_config(d.pop("content_config", UNSET))

        def _parse_remote_channel_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        remote_channel_id = _parse_remote_channel_id(d.pop("remote_channel_id", UNSET))

        notification_template_response = cls(
            id=id,
            title=title,
            channel_hint=channel_hint,
            events=events,
            visibility=visibility,
            is_active=is_active,
            created_at=created_at,
            updated_at=updated_at,
            domain_name=domain_name,
            watched_item_id=watched_item_id,
            content_config=content_config,
            remote_channel_id=remote_channel_id,
        )

        notification_template_response.additional_properties = d
        return notification_template_response

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
