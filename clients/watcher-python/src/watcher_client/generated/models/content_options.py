from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ContentOptions")


@_attrs_define
class ContentOptions:
    """Field toggles controlling what extra information appears in a notification body.

    The diff/significance toggles (`include_diff_snippet`, `diff_snippet_lines`,
    `include_diff_full`, `include_significance`) and the `include_change_dashboard_url`
    toggle were removed in #221: the diff pipeline was dropped in Phase 5 (#156),
    so those had no observable effect, and the dashboard-URL toggle duplicated the
    always-present ITEM link. Diff restoration is tracked in #222.

        Attributes:
            include_temporal_context (bool | Unset):  Default: False.
            include_domain (bool | Unset):  Default: False.
            include_last_changed_at (bool | Unset):  Default: False.
            include_tags (bool | Unset):  Default: False.
            include_description (bool | Unset):  Default: False.
            title_template (None | str | Unset):
            body_template (None | str | Unset):
    """

    include_temporal_context: bool | Unset = False
    include_domain: bool | Unset = False
    include_last_changed_at: bool | Unset = False
    include_tags: bool | Unset = False
    include_description: bool | Unset = False
    title_template: None | str | Unset = UNSET
    body_template: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        include_temporal_context = self.include_temporal_context

        include_domain = self.include_domain

        include_last_changed_at = self.include_last_changed_at

        include_tags = self.include_tags

        include_description = self.include_description

        title_template: None | str | Unset
        if isinstance(self.title_template, Unset):
            title_template = UNSET
        else:
            title_template = self.title_template

        body_template: None | str | Unset
        if isinstance(self.body_template, Unset):
            body_template = UNSET
        else:
            body_template = self.body_template

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if include_temporal_context is not UNSET:
            field_dict["include_temporal_context"] = include_temporal_context
        if include_domain is not UNSET:
            field_dict["include_domain"] = include_domain
        if include_last_changed_at is not UNSET:
            field_dict["include_last_changed_at"] = include_last_changed_at
        if include_tags is not UNSET:
            field_dict["include_tags"] = include_tags
        if include_description is not UNSET:
            field_dict["include_description"] = include_description
        if title_template is not UNSET:
            field_dict["title_template"] = title_template
        if body_template is not UNSET:
            field_dict["body_template"] = body_template

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        include_temporal_context = d.pop("include_temporal_context", UNSET)

        include_domain = d.pop("include_domain", UNSET)

        include_last_changed_at = d.pop("include_last_changed_at", UNSET)

        include_tags = d.pop("include_tags", UNSET)

        include_description = d.pop("include_description", UNSET)

        def _parse_title_template(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title_template = _parse_title_template(d.pop("title_template", UNSET))

        def _parse_body_template(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        body_template = _parse_body_template(d.pop("body_template", UNSET))

        content_options = cls(
            include_temporal_context=include_temporal_context,
            include_domain=include_domain,
            include_last_changed_at=include_last_changed_at,
            include_tags=include_tags,
            include_description=include_description,
            title_template=title_template,
            body_template=body_template,
        )

        content_options.additional_properties = d
        return content_options

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
