from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

if TYPE_CHECKING:
    from ..models.rep_spec_out_document import RepSpecOutDocument


T = TypeVar("T", bound="RepSpecOut")


@_attrs_define
class RepSpecOut:
    """Projection of a rep_specs row.

    Attributes:
        created_at (datetime.datetime):
        document (RepSpecOutDocument):
        name (str):
        provider (str):
        rep_spec_id (str):
        schema_version (int):
    """

    created_at: datetime.datetime
    document: RepSpecOutDocument
    name: str
    provider: str
    rep_spec_id: str
    schema_version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        document = self.document.to_dict()

        name = self.name

        provider = self.provider

        rep_spec_id = self.rep_spec_id

        schema_version = self.schema_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "document": document,
                "name": name,
                "provider": provider,
                "rep_spec_id": rep_spec_id,
                "schema_version": schema_version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.rep_spec_out_document import RepSpecOutDocument

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        document = RepSpecOutDocument.from_dict(d.pop("document"))

        name = d.pop("name")

        provider = d.pop("provider")

        rep_spec_id = d.pop("rep_spec_id")

        schema_version = d.pop("schema_version")

        rep_spec_out = cls(
            created_at=created_at,
            document=document,
            name=name,
            provider=provider,
            rep_spec_id=rep_spec_id,
            schema_version=schema_version,
        )

        rep_spec_out.additional_properties = d
        return rep_spec_out

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
