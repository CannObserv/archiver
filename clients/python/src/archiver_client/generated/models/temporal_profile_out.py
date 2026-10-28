from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..models.temporal_profile_out_post_action import TemporalProfileOutPostAction
from ..models.temporal_profile_out_profile_type import TemporalProfileOutProfileType

if TYPE_CHECKING:
    from ..models.temporal_profile_out_rules_item import TemporalProfileOutRulesItem


T = TypeVar("T", bound="TemporalProfileOut")


@_attrs_define
class TemporalProfileOut:
    """An InfoItem's temporal profile, with the result it resolved to last.

    Attributes:
        created_at (datetime.datetime):
        date_range_end (datetime.date | None):
        date_range_start (datetime.date | None):
        evaluated_on (datetime.date): The UTC day resolved_interval was computed for: the last write or daily boundary.
        fired_at (datetime.datetime | None): When the post-action fired; null while it has not. A PUT clears it.
        info_item_id (str):
        is_active (bool):
        post_action (TemporalProfileOutPostAction):
        profile_type (TemporalProfileOutProfileType):
        reference_date (datetime.date | None):
        resolved_interval (None | str): The interval the profile contributes as of evaluated_on: the top tier of the
            announced cadence. null contributes none.
        rules (list[TemporalProfileOutRulesItem]): As stored: TemporalProfileRule objects (untyped here so a hand-edited
            row still reads back).
        updated_at (datetime.datetime):
    """

    created_at: datetime.datetime
    date_range_end: datetime.date | None
    date_range_start: datetime.date | None
    evaluated_on: datetime.date
    fired_at: datetime.datetime | None
    info_item_id: str
    is_active: bool
    post_action: TemporalProfileOutPostAction
    profile_type: TemporalProfileOutProfileType
    reference_date: datetime.date | None
    resolved_interval: None | str
    rules: list[TemporalProfileOutRulesItem]
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        date_range_end: None | str
        if isinstance(self.date_range_end, datetime.date):
            date_range_end = self.date_range_end.isoformat()
        else:
            date_range_end = self.date_range_end

        date_range_start: None | str
        if isinstance(self.date_range_start, datetime.date):
            date_range_start = self.date_range_start.isoformat()
        else:
            date_range_start = self.date_range_start

        evaluated_on = self.evaluated_on.isoformat()

        fired_at: None | str
        if isinstance(self.fired_at, datetime.datetime):
            fired_at = self.fired_at.isoformat()
        else:
            fired_at = self.fired_at

        info_item_id = self.info_item_id

        is_active = self.is_active

        post_action = self.post_action.value

        profile_type = self.profile_type.value

        reference_date: None | str
        if isinstance(self.reference_date, datetime.date):
            reference_date = self.reference_date.isoformat()
        else:
            reference_date = self.reference_date

        resolved_interval: None | str
        resolved_interval = self.resolved_interval

        rules = []
        for rules_item_data in self.rules:
            rules_item = rules_item_data.to_dict()
            rules.append(rules_item)

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "date_range_end": date_range_end,
                "date_range_start": date_range_start,
                "evaluated_on": evaluated_on,
                "fired_at": fired_at,
                "info_item_id": info_item_id,
                "is_active": is_active,
                "post_action": post_action,
                "profile_type": profile_type,
                "reference_date": reference_date,
                "resolved_interval": resolved_interval,
                "rules": rules,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.temporal_profile_out_rules_item import TemporalProfileOutRulesItem

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_date_range_end(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_end_type_0 = isoparse(data).date()

                return date_range_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        date_range_end = _parse_date_range_end(d.pop("date_range_end"))

        def _parse_date_range_start(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_start_type_0 = isoparse(data).date()

                return date_range_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        date_range_start = _parse_date_range_start(d.pop("date_range_start"))

        evaluated_on = isoparse(d.pop("evaluated_on")).date()

        def _parse_fired_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                fired_at_type_0 = isoparse(data)

                return fired_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        fired_at = _parse_fired_at(d.pop("fired_at"))

        info_item_id = d.pop("info_item_id")

        is_active = d.pop("is_active")

        post_action = TemporalProfileOutPostAction(d.pop("post_action"))

        profile_type = TemporalProfileOutProfileType(d.pop("profile_type"))

        def _parse_reference_date(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reference_date_type_0 = isoparse(data).date()

                return reference_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        reference_date = _parse_reference_date(d.pop("reference_date"))

        def _parse_resolved_interval(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        resolved_interval = _parse_resolved_interval(d.pop("resolved_interval"))

        rules = []
        _rules = d.pop("rules")
        for rules_item_data in _rules:
            rules_item = TemporalProfileOutRulesItem.from_dict(rules_item_data)

            rules.append(rules_item)

        updated_at = isoparse(d.pop("updated_at"))

        temporal_profile_out = cls(
            created_at=created_at,
            date_range_end=date_range_end,
            date_range_start=date_range_start,
            evaluated_on=evaluated_on,
            fired_at=fired_at,
            info_item_id=info_item_id,
            is_active=is_active,
            post_action=post_action,
            profile_type=profile_type,
            reference_date=reference_date,
            resolved_interval=resolved_interval,
            rules=rules,
            updated_at=updated_at,
        )

        temporal_profile_out.additional_properties = d
        return temporal_profile_out

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
