from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ContentOptions")


@_attrs_define
class ContentOptions:
    """Field toggles for one event's notification body, and optional Jinja overrides.

    Attributes:
        body_template (None | str | Unset):
        diff_snippet_lines (int | Unset):  Default: 25.
        include_description (bool | Unset):  Default: False.
        include_diff_full (bool | Unset):  Default: False.
        include_diff_snippet (bool | Unset):  Default: True.
        include_domain (bool | Unset):  Default: False.
        include_last_changed_at (bool | Unset):  Default: False.
        include_tags (bool | Unset):  Default: False.
        include_temporal_context (bool | Unset):  Default: False.
        title_template (None | str | Unset):
    """

    body_template: None | str | Unset = UNSET
    diff_snippet_lines: int | Unset = 25
    include_description: bool | Unset = False
    include_diff_full: bool | Unset = False
    include_diff_snippet: bool | Unset = True
    include_domain: bool | Unset = False
    include_last_changed_at: bool | Unset = False
    include_tags: bool | Unset = False
    include_temporal_context: bool | Unset = False
    title_template: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        body_template: None | str | Unset
        if isinstance(self.body_template, Unset):
            body_template = UNSET
        else:
            body_template = self.body_template

        diff_snippet_lines = self.diff_snippet_lines

        include_description = self.include_description

        include_diff_full = self.include_diff_full

        include_diff_snippet = self.include_diff_snippet

        include_domain = self.include_domain

        include_last_changed_at = self.include_last_changed_at

        include_tags = self.include_tags

        include_temporal_context = self.include_temporal_context

        title_template: None | str | Unset
        if isinstance(self.title_template, Unset):
            title_template = UNSET
        else:
            title_template = self.title_template

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if body_template is not UNSET:
            field_dict["body_template"] = body_template
        if diff_snippet_lines is not UNSET:
            field_dict["diff_snippet_lines"] = diff_snippet_lines
        if include_description is not UNSET:
            field_dict["include_description"] = include_description
        if include_diff_full is not UNSET:
            field_dict["include_diff_full"] = include_diff_full
        if include_diff_snippet is not UNSET:
            field_dict["include_diff_snippet"] = include_diff_snippet
        if include_domain is not UNSET:
            field_dict["include_domain"] = include_domain
        if include_last_changed_at is not UNSET:
            field_dict["include_last_changed_at"] = include_last_changed_at
        if include_tags is not UNSET:
            field_dict["include_tags"] = include_tags
        if include_temporal_context is not UNSET:
            field_dict["include_temporal_context"] = include_temporal_context
        if title_template is not UNSET:
            field_dict["title_template"] = title_template

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_body_template(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        body_template = _parse_body_template(d.pop("body_template", UNSET))

        diff_snippet_lines = d.pop("diff_snippet_lines", UNSET)

        include_description = d.pop("include_description", UNSET)

        include_diff_full = d.pop("include_diff_full", UNSET)

        include_diff_snippet = d.pop("include_diff_snippet", UNSET)

        include_domain = d.pop("include_domain", UNSET)

        include_last_changed_at = d.pop("include_last_changed_at", UNSET)

        include_tags = d.pop("include_tags", UNSET)

        include_temporal_context = d.pop("include_temporal_context", UNSET)

        def _parse_title_template(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title_template = _parse_title_template(d.pop("title_template", UNSET))

        content_options = cls(
            body_template=body_template,
            diff_snippet_lines=diff_snippet_lines,
            include_description=include_description,
            include_diff_full=include_diff_full,
            include_diff_snippet=include_diff_snippet,
            include_domain=include_domain,
            include_last_changed_at=include_last_changed_at,
            include_tags=include_tags,
            include_temporal_context=include_temporal_context,
            title_template=title_template,
        )

        return content_options
