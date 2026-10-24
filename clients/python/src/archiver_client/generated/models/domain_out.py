from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

if TYPE_CHECKING:
    from ..models.domain_out_default_watch_spec_type_0 import DomainOutDefaultWatchSpecType0


T = TypeVar("T", bound="DomainOut")


@_attrs_define
class DomainOut:
    """Projection of a domains row.

    Attributes:
        archived_at (datetime.datetime | None): Set when the domain is archived; an archived host is suspended.
        created_at (datetime.datetime): UTC timestamp when the Domain was created.
        default_watch_spec (DomainOutDefaultWatchSpecType0 | None): Default cadence for Information Items on this host:
            a WatchSpec v1 document that carries an interval, or null for no domain default. Dark until cadence resolution
            (#364, flip F2) reads it.
        id (str): ULID identifying this Domain.
        is_active (bool): Suspension lever (archiver#360). false suspends the host: every Information Item announced on
            it goes out with active=false on info.registry, whatever its own watch_active. Archiving suspends it too.
        min_interval_seconds (float): Minimum spacing between requests to this host, in seconds (finite, >= 0; default
            1.0). Dark until Archiver produces content.fetch-policy (#366, flip F1): until then Watcher's value is live, and
            the re-import before F1 overwrites an edit made here.
        name (str): Hostname (e.g. regulations.cannabis.ca.gov).
        notes (None | str): Operator annotations.
        updated_at (datetime.datetime): UTC timestamp of the last update.
    """

    archived_at: datetime.datetime | None
    created_at: datetime.datetime
    default_watch_spec: DomainOutDefaultWatchSpecType0 | None
    id: str
    is_active: bool
    min_interval_seconds: float
    name: str
    notes: None | str
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.domain_out_default_watch_spec_type_0 import DomainOutDefaultWatchSpecType0

        archived_at: None | str
        if isinstance(self.archived_at, datetime.datetime):
            archived_at = self.archived_at.isoformat()
        else:
            archived_at = self.archived_at

        created_at = self.created_at.isoformat()

        default_watch_spec: dict[str, Any] | None
        if isinstance(self.default_watch_spec, DomainOutDefaultWatchSpecType0):
            default_watch_spec = self.default_watch_spec.to_dict()
        else:
            default_watch_spec = self.default_watch_spec

        id = self.id

        is_active = self.is_active

        min_interval_seconds = self.min_interval_seconds

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
                "default_watch_spec": default_watch_spec,
                "id": id,
                "is_active": is_active,
                "min_interval_seconds": min_interval_seconds,
                "name": name,
                "notes": notes,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.domain_out_default_watch_spec_type_0 import DomainOutDefaultWatchSpecType0

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

        def _parse_default_watch_spec(data: object) -> DomainOutDefaultWatchSpecType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_watch_spec_type_0 = DomainOutDefaultWatchSpecType0.from_dict(data)

                return default_watch_spec_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DomainOutDefaultWatchSpecType0 | None, data)

        default_watch_spec = _parse_default_watch_spec(d.pop("default_watch_spec"))

        id = d.pop("id")

        is_active = d.pop("is_active")

        min_interval_seconds = d.pop("min_interval_seconds")

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
            default_watch_spec=default_watch_spec,
            id=id,
            is_active=is_active,
            min_interval_seconds=min_interval_seconds,
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
