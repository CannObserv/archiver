from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="TemporalProfileRule")


@_attrs_define
class TemporalProfileRule:
    """One rule: from ``days_before`` the reference date, check every ``interval``.

    A seasonal profile takes exactly one rule, with no ``days_before``.

        Attributes:
            interval (str): A WatchSpec v1 interval ('30m', '6h', '1d'), greater than zero.
            days_before (int | None | Unset): event/deadline: the rule applies from this many days before the reference
                date. The smallest days_before still covering the day wins.
    """

    interval: str
    days_before: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        interval = self.interval

        days_before: int | None | Unset
        if isinstance(self.days_before, Unset):
            days_before = UNSET
        else:
            days_before = self.days_before

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "interval": interval,
            }
        )
        if days_before is not UNSET:
            field_dict["days_before"] = days_before

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        interval = d.pop("interval")

        def _parse_days_before(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        days_before = _parse_days_before(d.pop("days_before", UNSET))

        temporal_profile_rule = cls(
            interval=interval,
            days_before=days_before,
        )

        return temporal_profile_rule
