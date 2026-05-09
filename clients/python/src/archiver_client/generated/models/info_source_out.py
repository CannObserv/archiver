from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

if TYPE_CHECKING:
    from ..models.info_source_out_source_spec import InfoSourceOutSourceSpec


T = TypeVar("T", bound="InfoSourceOut")


@_attrs_define
class InfoSourceOut:
    """Projection of an info_sources row.

    Attributes:
        created_at (datetime.datetime):
        info_source_id (str):
        parent_info_source_id (None | str):
        schema_version (int):
        source_spec (InfoSourceOutSourceSpec):
        url (None | str):
    """

    created_at: datetime.datetime
    info_source_id: str
    parent_info_source_id: None | str
    schema_version: int
    source_spec: InfoSourceOutSourceSpec
    url: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        info_source_id = self.info_source_id

        parent_info_source_id: None | str
        parent_info_source_id = self.parent_info_source_id

        schema_version = self.schema_version

        source_spec = self.source_spec.to_dict()

        url: None | str
        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "info_source_id": info_source_id,
                "parent_info_source_id": parent_info_source_id,
                "schema_version": schema_version,
                "source_spec": source_spec,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_source_out_source_spec import InfoSourceOutSourceSpec

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        info_source_id = d.pop("info_source_id")

        def _parse_parent_info_source_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        parent_info_source_id = _parse_parent_info_source_id(d.pop("parent_info_source_id"))

        schema_version = d.pop("schema_version")

        source_spec = InfoSourceOutSourceSpec.from_dict(d.pop("source_spec"))

        def _parse_url(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        url = _parse_url(d.pop("url"))

        info_source_out = cls(
            created_at=created_at,
            info_source_id=info_source_id,
            parent_info_source_id=parent_info_source_id,
            schema_version=schema_version,
            source_spec=source_spec,
            url=url,
        )

        info_source_out.additional_properties = d
        return info_source_out

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
