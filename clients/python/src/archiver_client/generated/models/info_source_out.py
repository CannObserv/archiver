from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse


T = TypeVar("T", bound="InfoSourceOut")


@_attrs_define
class InfoSourceOut:
    """Projection of an info_sources row.

    Attributes:
        created_at (datetime.datetime):
        info_source_id (str):
        source_specs (list[Any]):
        url (str):
    """

    created_at: datetime.datetime
    info_source_id: str
    source_specs: list[Any]
    url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()
        info_source_id = self.info_source_id
        source_specs = self.source_specs
        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "info_source_id": info_source_id,
                "source_specs": source_specs,
                "url": url,
            }
        )
        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))
        info_source_id = d.pop("info_source_id")
        source_specs = d.pop("source_specs")
        url = d.pop("url")

        obj = cls(
            created_at=created_at,
            info_source_id=info_source_id,
            source_specs=source_specs,
            url=url,
        )
        obj.additional_properties = d
        return obj

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
