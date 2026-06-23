from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BodyDomainDefaultScheduleConfigUpdateDomainsNameDefaultScheduleConfigPost")


@_attrs_define
class BodyDomainDefaultScheduleConfigUpdateDomainsNameDefaultScheduleConfigPost:
    """
    Attributes:
        interval (str | Unset):  Default: ''.
    """

    interval: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        interval = self.interval

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if interval is not UNSET:
            field_dict["interval"] = interval

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        interval = d.pop("interval", UNSET)

        body_domain_default_schedule_config_update_domains_name_default_schedule_config_post = cls(
            interval=interval,
        )

        body_domain_default_schedule_config_update_domains_name_default_schedule_config_post.additional_properties = d
        return body_domain_default_schedule_config_update_domains_name_default_schedule_config_post

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
