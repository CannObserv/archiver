from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config_overrides import ContentConfigOverrides
    from ..models.content_options import ContentOptions


T = TypeVar("T", bound="ContentConfig")


@_attrs_define
class ContentConfig:
    """Per-config content customisation: default options with optional per-event overrides.

    Attributes:
        default (ContentOptions | Unset): Field toggles controlling what extra information appears in a notification
            body.

            The diff/significance toggles (`include_diff_snippet`, `diff_snippet_lines`,
            `include_diff_full`, `include_significance`) and the `include_change_dashboard_url`
            toggle were removed in #221: the diff pipeline was dropped in Phase 5 (#156),
            so those had no observable effect, and the dashboard-URL toggle duplicated the
            always-present ITEM link. Diff restoration is tracked in #222.
        overrides (ContentConfigOverrides | Unset):
    """

    default: ContentOptions | Unset = UNSET
    overrides: ContentConfigOverrides | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        default: dict[str, Any] | Unset = UNSET
        if not isinstance(self.default, Unset):
            default = self.default.to_dict()

        overrides: dict[str, Any] | Unset = UNSET
        if not isinstance(self.overrides, Unset):
            overrides = self.overrides.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if default is not UNSET:
            field_dict["default"] = default
        if overrides is not UNSET:
            field_dict["overrides"] = overrides

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.content_config_overrides import ContentConfigOverrides
        from ..models.content_options import ContentOptions

        d = dict(src_dict)
        _default = d.pop("default", UNSET)
        default: ContentOptions | Unset
        if isinstance(_default, Unset):
            default = UNSET
        else:
            default = ContentOptions.from_dict(_default)

        _overrides = d.pop("overrides", UNSET)
        overrides: ContentConfigOverrides | Unset
        if isinstance(_overrides, Unset):
            overrides = UNSET
        else:
            overrides = ContentConfigOverrides.from_dict(_overrides)

        content_config = cls(
            default=default,
            overrides=overrides,
        )

        content_config.additional_properties = d
        return content_config

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
