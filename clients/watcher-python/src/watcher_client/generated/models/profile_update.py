from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.post_action import PostAction
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.profile_rule_item import ProfileRuleItem


T = TypeVar("T", bound="ProfileUpdate")


@_attrs_define
class ProfileUpdate:
    """Schema for partially updating a temporal profile.

    Attributes:
        is_active (bool | None | Unset):
        rules (list[ProfileRuleItem] | None | Unset):
        post_action (None | PostAction | Unset):
    """

    is_active: bool | None | Unset = UNSET
    rules: list[ProfileRuleItem] | None | Unset = UNSET
    post_action: None | PostAction | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        is_active: bool | None | Unset
        if isinstance(self.is_active, Unset):
            is_active = UNSET
        else:
            is_active = self.is_active

        rules: list[dict[str, Any]] | None | Unset
        if isinstance(self.rules, Unset):
            rules = UNSET
        elif isinstance(self.rules, list):
            rules = []
            for rules_type_0_item_data in self.rules:
                rules_type_0_item = rules_type_0_item_data.to_dict()
                rules.append(rules_type_0_item)

        else:
            rules = self.rules

        post_action: None | str | Unset
        if isinstance(self.post_action, Unset):
            post_action = UNSET
        elif isinstance(self.post_action, PostAction):
            post_action = self.post_action.value
        else:
            post_action = self.post_action

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if rules is not UNSET:
            field_dict["rules"] = rules
        if post_action is not UNSET:
            field_dict["post_action"] = post_action

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.profile_rule_item import ProfileRuleItem

        d = dict(src_dict)

        def _parse_is_active(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_active = _parse_is_active(d.pop("is_active", UNSET))

        def _parse_rules(data: object) -> list[ProfileRuleItem] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                rules_type_0 = []
                _rules_type_0 = data
                for rules_type_0_item_data in _rules_type_0:
                    rules_type_0_item = ProfileRuleItem.from_dict(rules_type_0_item_data)

                    rules_type_0.append(rules_type_0_item)

                return rules_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ProfileRuleItem] | None | Unset, data)

        rules = _parse_rules(d.pop("rules", UNSET))

        def _parse_post_action(data: object) -> None | PostAction | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                post_action_type_0 = PostAction(data)

                return post_action_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PostAction | Unset, data)

        post_action = _parse_post_action(d.pop("post_action", UNSET))

        profile_update = cls(
            is_active=is_active,
            rules=rules,
            post_action=post_action,
        )

        profile_update.additional_properties = d
        return profile_update

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
