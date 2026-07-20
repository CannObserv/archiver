from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.rep_spec_out_document import RepSpecOutDocument


T = TypeVar("T", bound="RepSpecOut")


@_attrs_define
class RepSpecOut:
    """Projection of a rep_specs row.

    Attributes:
        created_at (datetime.datetime): UTC timestamp when the RepSpec was created.
        document (RepSpecOutDocument): RepSpec envelope document validated against rep_spec_schema/v1.json and the per-
            provider sub-schema.
        name (str): Operator-friendly label for this RepSpec.
        provider (str): Provider key (e.g. 'gcs', 'gdrive', 'ia').
        rep_spec_id (str): ULID identifying this RepSpec.
        schema_version (int): RepSpec envelope schema version; always 1 in the current implementation.
        updated_at (datetime.datetime | None | Unset): UTC timestamp of the last edit, or null if the RepSpec has never
            been edited. Never backfilled from created_at.
    """

    created_at: datetime.datetime
    document: RepSpecOutDocument
    name: str
    provider: str
    rep_spec_id: str
    schema_version: int
    updated_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        document = self.document.to_dict()

        name = self.name

        provider = self.provider

        rep_spec_id = self.rep_spec_id

        schema_version = self.schema_version

        updated_at: None | str | Unset
        if isinstance(self.updated_at, Unset):
            updated_at = UNSET
        elif isinstance(self.updated_at, datetime.datetime):
            updated_at = self.updated_at.isoformat()
        else:
            updated_at = self.updated_at

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
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at

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

        def _parse_updated_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                updated_at_type_0 = isoparse(data)

                return updated_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        updated_at = _parse_updated_at(d.pop("updated_at", UNSET))

        rep_spec_out = cls(
            created_at=created_at,
            document=document,
            name=name,
            provider=provider,
            rep_spec_id=rep_spec_id,
            schema_version=schema_version,
            updated_at=updated_at,
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
