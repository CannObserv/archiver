from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config import ContentConfig


T = TypeVar("T", bound="NotificationTemplateCreate")


@_attrs_define
class NotificationTemplateCreate:
    """`str_strip_whitespace` runs before length validation, so a
    whitespace-only `channel_hint` collapses to ``""`` and trips
    `min_length=1`.

        Attributes:
            title (str):
            remote_channel_id (str):
            channel_hint (str | Unset):  Default: 'remote'.
            events (list[str] | Unset):
            is_global_default (bool | Unset):  Default: False.
            content_config (ContentConfig | None | Unset):
    """

    title: str
    remote_channel_id: str
    channel_hint: str | Unset = "remote"
    events: list[str] | Unset = UNSET
    is_global_default: bool | Unset = False
    content_config: ContentConfig | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.content_config import ContentConfig

        title = self.title

        remote_channel_id = self.remote_channel_id

        channel_hint = self.channel_hint

        events: list[str] | Unset = UNSET
        if not isinstance(self.events, Unset):
            events = self.events

        is_global_default = self.is_global_default

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
                "title": title,
                "remote_channel_id": remote_channel_id,
            }
        )
        if channel_hint is not UNSET:
            field_dict["channel_hint"] = channel_hint
        if events is not UNSET:
            field_dict["events"] = events
        if is_global_default is not UNSET:
            field_dict["is_global_default"] = is_global_default
        if content_config is not UNSET:
            field_dict["content_config"] = content_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config import ContentConfig

        d = dict(src_dict)
        title = d.pop("title")

        remote_channel_id = d.pop("remote_channel_id")

        channel_hint = d.pop("channel_hint", UNSET)

        events = cast(list[str], d.pop("events", UNSET))

        is_global_default = d.pop("is_global_default", UNSET)

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

        notification_template_create = cls(
            title=title,
            remote_channel_id=remote_channel_id,
            channel_hint=channel_hint,
            events=events,
            is_global_default=is_global_default,
            content_config=content_config,
        )

        notification_template_create.additional_properties = d
        return notification_template_create

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
