from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.post_action import PostAction
from ..models.profile_type import ProfileType

T = TypeVar("T", bound="ProfileResponse")


@_attrs_define
class ProfileResponse:
    """Schema for returning a temporal profile.

    Attributes:
        id (str):
        watched_item_id (str):
        profile_type (ProfileType): Type of temporal profile controlling schedule escalation behavior.
        reference_date (datetime.date | None):
        date_range_start (datetime.date | None):
        date_range_end (datetime.date | None):
        rules (list[Any]):
        post_action (PostAction): Action taken after a temporal profile's date window passes.
        is_active (bool):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    id: str
    watched_item_id: str
    profile_type: ProfileType
    reference_date: datetime.date | None
    date_range_start: datetime.date | None
    date_range_end: datetime.date | None
    rules: list[Any]
    post_action: PostAction
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        watched_item_id = self.watched_item_id

        profile_type = self.profile_type.value

        reference_date: None | str
        if isinstance(self.reference_date, datetime.date):
            reference_date = self.reference_date.isoformat()
        else:
            reference_date = self.reference_date

        date_range_start: None | str
        if isinstance(self.date_range_start, datetime.date):
            date_range_start = self.date_range_start.isoformat()
        else:
            date_range_start = self.date_range_start

        date_range_end: None | str
        if isinstance(self.date_range_end, datetime.date):
            date_range_end = self.date_range_end.isoformat()
        else:
            date_range_end = self.date_range_end

        rules = self.rules

        post_action = self.post_action.value

        is_active = self.is_active

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "watched_item_id": watched_item_id,
                "profile_type": profile_type,
                "reference_date": reference_date,
                "date_range_start": date_range_start,
                "date_range_end": date_range_end,
                "rules": rules,
                "post_action": post_action,
                "is_active": is_active,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        watched_item_id = d.pop("watched_item_id")

        profile_type = ProfileType(d.pop("profile_type"))

        def _parse_reference_date(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reference_date_type_0 = datetime.date.fromisoformat(data)

                return reference_date_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        reference_date = _parse_reference_date(d.pop("reference_date"))

        def _parse_date_range_start(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_start_type_0 = datetime.date.fromisoformat(data)

                return date_range_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        date_range_start = _parse_date_range_start(d.pop("date_range_start"))

        def _parse_date_range_end(data: object) -> datetime.date | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_range_end_type_0 = datetime.date.fromisoformat(data)

                return date_range_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None, data)

        date_range_end = _parse_date_range_end(d.pop("date_range_end"))

        rules = cast(list[Any], d.pop("rules"))

        post_action = PostAction(d.pop("post_action"))

        is_active = d.pop("is_active")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        profile_response = cls(
            id=id,
            watched_item_id=watched_item_id,
            profile_type=profile_type,
            reference_date=reference_date,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            rules=rules,
            post_action=post_action,
            is_active=is_active,
            created_at=created_at,
            updated_at=updated_at,
        )

        profile_response.additional_properties = d
        return profile_response

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
