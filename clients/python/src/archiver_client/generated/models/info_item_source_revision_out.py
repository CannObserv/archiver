from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="InfoItemSourceRevisionOut")


@_attrs_define
class InfoItemSourceRevisionOut:
    """Projection of an info_item_source_revisions row.

    Attributes:
        bound_at (datetime.datetime):
        info_item_id (str):
        source_revision_id (str):
    """

    bound_at: datetime.datetime
    info_item_id: str
    source_revision_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bound_at = self.bound_at.isoformat()

        info_item_id = self.info_item_id

        source_revision_id = self.source_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bound_at": bound_at,
                "info_item_id": info_item_id,
                "source_revision_id": source_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        bound_at = isoparse(d.pop("bound_at"))

        info_item_id = d.pop("info_item_id")

        source_revision_id = d.pop("source_revision_id")

        info_item_source_revision_out = cls(
            bound_at=bound_at,
            info_item_id=info_item_id,
            source_revision_id=source_revision_id,
        )

        info_item_source_revision_out.additional_properties = d
        return info_item_source_revision_out

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
