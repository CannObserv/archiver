from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.domain_response_default_schedule_config_type_0 import (
        DomainResponseDefaultScheduleConfigType0,
    )


T = TypeVar("T", bound="DomainResponse")


@_attrs_define
class DomainResponse:
    """Schema for returning a domain config.

    Attributes:
        id (str):
        name (str):
        min_interval (float):
        max_concurrency (int):
        current_interval (float):
        last_request_at (datetime.datetime | None):
        decay_window (float):
        notes (None | str):
        default_schedule_config (DomainResponseDefaultScheduleConfigType0 | None):
        archived_at (datetime.datetime | None):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    id: str
    name: str
    min_interval: float
    max_concurrency: int
    current_interval: float
    last_request_at: datetime.datetime | None
    decay_window: float
    notes: None | str
    default_schedule_config: DomainResponseDefaultScheduleConfigType0 | None
    archived_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.domain_response_default_schedule_config_type_0 import (
            DomainResponseDefaultScheduleConfigType0,
        )

        id = self.id

        name = self.name

        min_interval = self.min_interval

        max_concurrency = self.max_concurrency

        current_interval = self.current_interval

        last_request_at: None | str
        if isinstance(self.last_request_at, datetime.datetime):
            last_request_at = self.last_request_at.isoformat()
        else:
            last_request_at = self.last_request_at

        decay_window = self.decay_window

        notes: None | str
        notes = self.notes

        default_schedule_config: dict[str, Any] | None
        if isinstance(self.default_schedule_config, DomainResponseDefaultScheduleConfigType0):
            default_schedule_config = self.default_schedule_config.to_dict()
        else:
            default_schedule_config = self.default_schedule_config

        archived_at: None | str
        if isinstance(self.archived_at, datetime.datetime):
            archived_at = self.archived_at.isoformat()
        else:
            archived_at = self.archived_at

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "min_interval": min_interval,
                "max_concurrency": max_concurrency,
                "current_interval": current_interval,
                "last_request_at": last_request_at,
                "decay_window": decay_window,
                "notes": notes,
                "default_schedule_config": default_schedule_config,
                "archived_at": archived_at,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.domain_response_default_schedule_config_type_0 import (
            DomainResponseDefaultScheduleConfigType0,
        )

        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        min_interval = d.pop("min_interval")

        max_concurrency = d.pop("max_concurrency")

        current_interval = d.pop("current_interval")

        def _parse_last_request_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_request_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_request_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_request_at = _parse_last_request_at(d.pop("last_request_at"))

        decay_window = d.pop("decay_window")

        def _parse_notes(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        notes = _parse_notes(d.pop("notes"))

        def _parse_default_schedule_config(
            data: object,
        ) -> DomainResponseDefaultScheduleConfigType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_schedule_config_type_0 = DomainResponseDefaultScheduleConfigType0.from_dict(
                    data
                )

                return default_schedule_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DomainResponseDefaultScheduleConfigType0 | None, data)

        default_schedule_config = _parse_default_schedule_config(d.pop("default_schedule_config"))

        def _parse_archived_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                archived_at_type_0 = datetime.datetime.fromisoformat(data)

                return archived_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        archived_at = _parse_archived_at(d.pop("archived_at"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        domain_response = cls(
            id=id,
            name=name,
            min_interval=min_interval,
            max_concurrency=max_concurrency,
            current_interval=current_interval,
            last_request_at=last_request_at,
            decay_window=decay_window,
            notes=notes,
            default_schedule_config=default_schedule_config,
            archived_at=archived_at,
            created_at=created_at,
            updated_at=updated_at,
        )

        domain_response.additional_properties = d
        return domain_response

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
