from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.domain_patch_default_schedule_config_type_0 import (
        DomainPatchDefaultScheduleConfigType0,
    )


T = TypeVar("T", bound="DomainPatch")


@_attrs_define
class DomainPatch:
    """Schema for creating or updating a domain config (upsert via PATCH).

    Attributes:
        min_interval (float | None | Unset):
        max_concurrency (int | None | Unset):
        decay_window (float | None | Unset):
        notes (None | str | Unset):
        default_schedule_config (DomainPatchDefaultScheduleConfigType0 | None | Unset):
    """

    min_interval: float | None | Unset = UNSET
    max_concurrency: int | None | Unset = UNSET
    decay_window: float | None | Unset = UNSET
    notes: None | str | Unset = UNSET
    default_schedule_config: DomainPatchDefaultScheduleConfigType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.domain_patch_default_schedule_config_type_0 import (
            DomainPatchDefaultScheduleConfigType0,
        )

        min_interval: float | None | Unset
        if isinstance(self.min_interval, Unset):
            min_interval = UNSET
        else:
            min_interval = self.min_interval

        max_concurrency: int | None | Unset
        if isinstance(self.max_concurrency, Unset):
            max_concurrency = UNSET
        else:
            max_concurrency = self.max_concurrency

        decay_window: float | None | Unset
        if isinstance(self.decay_window, Unset):
            decay_window = UNSET
        else:
            decay_window = self.decay_window

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        default_schedule_config: dict[str, Any] | None | Unset
        if isinstance(self.default_schedule_config, Unset):
            default_schedule_config = UNSET
        elif isinstance(self.default_schedule_config, DomainPatchDefaultScheduleConfigType0):
            default_schedule_config = self.default_schedule_config.to_dict()
        else:
            default_schedule_config = self.default_schedule_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if min_interval is not UNSET:
            field_dict["min_interval"] = min_interval
        if max_concurrency is not UNSET:
            field_dict["max_concurrency"] = max_concurrency
        if decay_window is not UNSET:
            field_dict["decay_window"] = decay_window
        if notes is not UNSET:
            field_dict["notes"] = notes
        if default_schedule_config is not UNSET:
            field_dict["default_schedule_config"] = default_schedule_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.domain_patch_default_schedule_config_type_0 import (
            DomainPatchDefaultScheduleConfigType0,
        )

        d = dict(src_dict)

        def _parse_min_interval(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        min_interval = _parse_min_interval(d.pop("min_interval", UNSET))

        def _parse_max_concurrency(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        max_concurrency = _parse_max_concurrency(d.pop("max_concurrency", UNSET))

        def _parse_decay_window(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        decay_window = _parse_decay_window(d.pop("decay_window", UNSET))

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        def _parse_default_schedule_config(
            data: object,
        ) -> DomainPatchDefaultScheduleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                default_schedule_config_type_0 = DomainPatchDefaultScheduleConfigType0.from_dict(
                    data
                )

                return default_schedule_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DomainPatchDefaultScheduleConfigType0 | None | Unset, data)

        default_schedule_config = _parse_default_schedule_config(
            d.pop("default_schedule_config", UNSET)
        )

        domain_patch = cls(
            min_interval=min_interval,
            max_concurrency=max_concurrency,
            decay_window=decay_window,
            notes=notes,
            default_schedule_config=default_schedule_config,
        )

        domain_patch.additional_properties = d
        return domain_patch

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
