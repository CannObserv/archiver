from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="DomainOut")


@_attrs_define
class DomainOut:
    """Projection of a domains row.

    Attributes:
        archived_at (datetime.datetime | None): Set when the domain is archived.
        created_at (datetime.datetime): UTC timestamp when the Domain was created.
        id (str): ULID identifying this Domain.
        is_active (bool): True when active and included in suggestions.
        name (str): Hostname (e.g. regulations.cannabis.ca.gov).
        notes (None | str): Operator annotations.
        updated_at (datetime.datetime): UTC timestamp of the last update.
    """

    archived_at: datetime.datetime | None
    created_at: datetime.datetime
    id: str
    is_active: bool
    name: str
    notes: None | str
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        archived_at: None | str
        if isinstance(self.archived_at, datetime.datetime):
            archived_at = self.archived_at.isoformat()
        else:
            archived_at = self.archived_at

        created_at = self.created_at.isoformat()

        id = self.id

        is_active = self.is_active

        name = self.name

        notes: None | str
        notes = self.notes

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "archived_at": archived_at,
                "created_at": created_at,
                "id": id,
                "is_active": is_active,
                "name": name,
                "notes": notes,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_archived_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                archived_at_type_0 = isoparse(data)

                return archived_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        archived_at = _parse_archived_at(d.pop("archived_at"))

        created_at = isoparse(d.pop("created_at"))

        id = d.pop("id")

        is_active = d.pop("is_active")

        name = d.pop("name")

        def _parse_notes(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        notes = _parse_notes(d.pop("notes"))

        updated_at = isoparse(d.pop("updated_at"))

        domain_out = cls(
            archived_at=archived_at,
            created_at=created_at,
            id=id,
            is_active=is_active,
            name=name,
            notes=notes,
            updated_at=updated_at,
        )

        domain_out.additional_properties = d
        return domain_out

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
