from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="InfoItemSourceRevisionCreate")


@_attrs_define
class InfoItemSourceRevisionCreate:
    """Request body for POST /info-items/{id}/source-revisions.

    Attributes:
        source_revision_id (str): ULID of an existing SourceRevision.
        bound_at (datetime.datetime | None | Unset): Bind timestamp; defaults to now() when omitted.
    """

    source_revision_id: str
    bound_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_revision_id = self.source_revision_id

        bound_at: None | str | Unset
        if isinstance(self.bound_at, Unset):
            bound_at = UNSET
        elif isinstance(self.bound_at, datetime.datetime):
            bound_at = self.bound_at.isoformat()
        else:
            bound_at = self.bound_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_revision_id": source_revision_id,
            }
        )
        if bound_at is not UNSET:
            field_dict["bound_at"] = bound_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_revision_id = d.pop("source_revision_id")

        def _parse_bound_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                bound_at_type_0 = isoparse(data)

                return bound_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        bound_at = _parse_bound_at(d.pop("bound_at", UNSET))

        info_item_source_revision_create = cls(
            source_revision_id=source_revision_id,
            bound_at=bound_at,
        )

        info_item_source_revision_create.additional_properties = d
        return info_item_source_revision_create

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
