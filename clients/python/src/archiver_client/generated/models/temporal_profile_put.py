from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from dateutil.parser import isoparse

from ..models.temporal_profile_put_post_action import TemporalProfilePutPostAction
from ..models.temporal_profile_put_profile_type import TemporalProfilePutProfileType
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.temporal_profile_rule import TemporalProfileRule


T = TypeVar("T", bound="TemporalProfilePut")


@_attrs_define
class TemporalProfilePut:
    """Request body for PUT /info-items/{id}/temporal-profile: the whole profile.

    A create-or-replace, never a merge. ``event`` and ``deadline`` take a
    ``reference_date`` and no range; ``seasonal`` takes an inclusive range and
    no ``reference_date``. Dates are UTC calendar days and absolute: nothing
    recurs yearly. A profile whose window has already ended is refused - every
    accepted write re-arms the post-action, which would then fire again.

        Attributes:
            post_action (TemporalProfilePutPostAction): Fired once, at the first daily boundary after the window:
                reduce_frequency sets the item's own interval to 1d if its base cadence is faster; deactivate pauses the item;
                archive archives its watch.
            profile_type (TemporalProfilePutProfileType):
            date_range_end (datetime.date | None | Unset):
            date_range_start (datetime.date | None | Unset):
            is_active (bool | Unset): The operator's switch: an inactive profile contributes no interval and never fires.
                Default: True.
            reference_date (datetime.date | None | Unset):
            rules (list[TemporalProfileRule] | Unset):
    """

    post_action: TemporalProfilePutPostAction
    profile_type: TemporalProfilePutProfileType
    date_range_end: datetime.date | None | Unset = UNSET
    date_range_start: datetime.date | None | Unset = UNSET
    is_active: bool | Unset = True
    reference_date: datetime.date | None | Unset = UNSET
    rules: list[TemporalProfileRule] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        post_action = self.post_action.value

        profile_type = self.profile_type.value

        date_range_end: None | str | Unset
        if isinstance(self.date_range_end, Unset):
            date_range_end = UNSET
        elif isinstance(self.date_range_end, datetime.date):
            date_range_end = self.date_range_end.isoformat()
        else:
            date_range_end = self.date_range_end

        date_range_start: None | str | Unset
        if isinstance(self.date_range_start, Unset):
            date_range_start = UNSET
        elif isinstance(self.date_range_start, datetime.date):
            date_range_start = self.date_range_start.isoformat()
        else:
            date_range_start = self.date_range_start

        is_active = self.is_active

        reference_date: None | str | Unset
        if isinstance(self.reference_date, Unset):
            reference_date = UNSET
        elif isinstance(self.reference_date, datetime.date):
            reference_date = self.reference_date.isoformat()
        else:
            reference_date = self.reference_date

        rules: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.rules, Unset):
            rules = []
            for rules_item_data in self.rules:
                rules_item = rules_item_data.to_dict()
                rules.append(rules_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "post_action": post_action,
                "profile_type": profile_type,
            }
        )
        if date_range_end is not UNSET:
            field_dict["date_range_end"] = date_range_end
        if date_range_start is not UNSET:
            field_dict["date_range_start"] = date_range_start
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if reference_date is not UNSET:
            field_dict["reference_date"] = reference_date
        if rules is not UNSET:
            field_dict["rules"] = rules

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.temporal_profile_rule import TemporalProfileRule

        d = dict(src_dict)
        post_action = TemporalProfilePutPostAction(d.pop("post_action"))

        profile_type = TemporalProfilePutProfileType(d.pop("profile_type"))

        def _parse_date_range_end(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_end_type_0 = isoparse(data).date()

                return date_range_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        date_range_end = _parse_date_range_end(d.pop("date_range_end", UNSET))

        def _parse_date_range_start(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_start_type_0 = isoparse(data).date()

                return date_range_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        date_range_start = _parse_date_range_start(d.pop("date_range_start", UNSET))

        is_active = d.pop("is_active", UNSET)

        def _parse_reference_date(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reference_date_type_0 = isoparse(data).date()

                return reference_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        reference_date = _parse_reference_date(d.pop("reference_date", UNSET))

        _rules = d.pop("rules", UNSET)
        rules: list[TemporalProfileRule] | Unset = UNSET
        if _rules is not UNSET:
            rules = []
            for rules_item_data in _rules:
                rules_item = TemporalProfileRule.from_dict(rules_item_data)

                rules.append(rules_item)

        temporal_profile_put = cls(
            post_action=post_action,
            profile_type=profile_type,
            date_range_end=date_range_end,
            date_range_start=date_range_start,
            is_active=is_active,
            reference_date=reference_date,
            rules=rules,
        )

        return temporal_profile_put
