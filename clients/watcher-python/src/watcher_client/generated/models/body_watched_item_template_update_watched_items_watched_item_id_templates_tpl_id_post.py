from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost")


@_attrs_define
class BodyWatchedItemTemplateUpdateWatchedItemsWatchedItemIdTemplatesTplIdPost:
    """
    Attributes:
        channel_hint (str):
        title (str | Unset):  Default: ''.
        events (str | Unset):  Default: 'change_detected'.
    """

    channel_hint: str
    title: str | Unset = ""
    events: str | Unset = "change_detected"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channel_hint = self.channel_hint

        title = self.title

        events = self.events

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "channel_hint": channel_hint,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if events is not UNSET:
            field_dict["events"] = events

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        channel_hint = d.pop("channel_hint")

        title = d.pop("title", UNSET)

        events = d.pop("events", UNSET)

        body_watched_item_template_update_watched_items_watched_item_id_templates_tpl_id_post = cls(
            channel_hint=channel_hint,
            title=title,
            events=events,
        )

        body_watched_item_template_update_watched_items_watched_item_id_templates_tpl_id_post.additional_properties = d
        return body_watched_item_template_update_watched_items_watched_item_id_templates_tpl_id_post

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
