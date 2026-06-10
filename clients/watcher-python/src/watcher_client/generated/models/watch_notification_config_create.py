from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config import ContentConfig


T = TypeVar("T", bound="WatchNotificationConfigCreate")


@_attrs_define
class WatchNotificationConfigCreate:
    """Request body for creating a notification config.

    `remote_channel_id` is the notifier-service channel ULID; required.
    `str_strip_whitespace` runs before length validation, so a
    whitespace-only `channel_hint` collapses to ``""`` and trips
    `min_length=1`.

        Attributes:
            remote_channel_id (str):
            channel_hint (str | Unset):  Default: 'remote'.
            title (None | str | Unset):
            events (list[str] | Unset):
            content_config (ContentConfig | None | Unset):
    """

    remote_channel_id: str
    channel_hint: str | Unset = "remote"
    title: None | str | Unset = UNSET
    events: list[str] | Unset = UNSET
    content_config: ContentConfig | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.content_config import ContentConfig

        remote_channel_id = self.remote_channel_id

        channel_hint = self.channel_hint

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        events: list[str] | Unset = UNSET
        if not isinstance(self.events, Unset):
            events = self.events

        content_config: dict[str, Any] | None | Unset
        if isinstance(self.content_config, Unset):
            content_config = UNSET
        elif isinstance(self.content_config, ContentConfig):
            content_config = self.content_config.to_dict()
        else:
            content_config = self.content_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "remote_channel_id": remote_channel_id,
            }
        )
        if channel_hint is not UNSET:
            field_dict["channel_hint"] = channel_hint
        if title is not UNSET:
            field_dict["title"] = title
        if events is not UNSET:
            field_dict["events"] = events
        if content_config is not UNSET:
            field_dict["content_config"] = content_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config import ContentConfig

        d = dict(src_dict)
        remote_channel_id = d.pop("remote_channel_id")

        channel_hint = d.pop("channel_hint", UNSET)

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        events = cast(list[str], d.pop("events", UNSET))

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

        watch_notification_config_create = cls(
            remote_channel_id=remote_channel_id,
            channel_hint=channel_hint,
            title=title,
            events=events,
            content_config=content_config,
        )

        watch_notification_config_create.additional_properties = d
        return watch_notification_config_create

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
