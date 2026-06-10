from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.post_action import PostAction
from ..models.profile_type import ProfileType
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.profile_rule_item import ProfileRuleItem


T = TypeVar("T", bound="ProfileCreate")


@_attrs_define
class ProfileCreate:
    """Schema for creating a temporal profile.

    Attributes:
        profile_type (ProfileType): Type of temporal profile controlling schedule escalation behavior.
        post_action (PostAction): Action taken after a temporal profile's date window passes.
        reference_date (datetime.date | None | Unset):
        date_range_start (datetime.date | None | Unset):
        date_range_end (datetime.date | None | Unset):
        rules (list[ProfileRuleItem] | Unset):
    """

    profile_type: ProfileType
    post_action: PostAction
    reference_date: datetime.date | None | Unset = UNSET
    date_range_start: datetime.date | None | Unset = UNSET
    date_range_end: datetime.date | None | Unset = UNSET
    rules: list[ProfileRuleItem] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        profile_type = self.profile_type.value

        post_action = self.post_action.value

        reference_date: None | str | Unset
        if isinstance(self.reference_date, Unset):
            reference_date = UNSET
        elif isinstance(self.reference_date, datetime.date):
            reference_date = self.reference_date.isoformat()
        else:
            reference_date = self.reference_date

        date_range_start: None | str | Unset
        if isinstance(self.date_range_start, Unset):
            date_range_start = UNSET
        elif isinstance(self.date_range_start, datetime.date):
            date_range_start = self.date_range_start.isoformat()
        else:
            date_range_start = self.date_range_start

        date_range_end: None | str | Unset
        if isinstance(self.date_range_end, Unset):
            date_range_end = UNSET
        elif isinstance(self.date_range_end, datetime.date):
            date_range_end = self.date_range_end.isoformat()
        else:
            date_range_end = self.date_range_end

        rules: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.rules, Unset):
            rules = []
            for rules_item_data in self.rules:
                rules_item = rules_item_data.to_dict()
                rules.append(rules_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "profile_type": profile_type,
                "post_action": post_action,
            }
        )
        if reference_date is not UNSET:
            field_dict["reference_date"] = reference_date
        if date_range_start is not UNSET:
            field_dict["date_range_start"] = date_range_start
        if date_range_end is not UNSET:
            field_dict["date_range_end"] = date_range_end
        if rules is not UNSET:
            field_dict["rules"] = rules

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.profile_rule_item import ProfileRuleItem

        d = dict(src_dict)
        profile_type = ProfileType(d.pop("profile_type"))

        post_action = PostAction(d.pop("post_action"))

        def _parse_reference_date(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reference_date_type_0 = datetime.date.fromisoformat(data)

                return reference_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        reference_date = _parse_reference_date(d.pop("reference_date", UNSET))

        def _parse_date_range_start(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_start_type_0 = datetime.date.fromisoformat(data)

                return date_range_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        date_range_start = _parse_date_range_start(d.pop("date_range_start", UNSET))

        def _parse_date_range_end(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_end_type_0 = datetime.date.fromisoformat(data)

                return date_range_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        date_range_end = _parse_date_range_end(d.pop("date_range_end", UNSET))

        _rules = d.pop("rules", UNSET)
        rules: list[ProfileRuleItem] | Unset = UNSET
        if _rules is not UNSET:
            rules = []
            for rules_item_data in _rules:
                rules_item = ProfileRuleItem.from_dict(rules_item_data)

                rules.append(rules_item)

        profile_create = cls(
            profile_type=profile_type,
            post_action=post_action,
            reference_date=reference_date,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            rules=rules,
        )

        profile_create.additional_properties = d
        return profile_create

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
