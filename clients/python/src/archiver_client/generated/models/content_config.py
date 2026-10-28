from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.content_config_overrides import ContentConfigOverrides
    from ..models.content_options import ContentOptions


T = TypeVar("T", bound="ContentConfig")


@_attrs_define
class ContentConfig:
    """Default options, with per-event overrides keyed by event name.

    Attributes:
        default (ContentOptions | Unset): Field toggles for one event's notification body, and optional Jinja overrides.
        overrides (ContentConfigOverrides | Unset):
    """

    default: ContentOptions | Unset = UNSET
    overrides: ContentConfigOverrides | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        default: dict[str, Any] | Unset = UNSET
        if not isinstance(self.default, Unset):
            default = self.default.to_dict()

        overrides: dict[str, Any] | Unset = UNSET
        if not isinstance(self.overrides, Unset):
            overrides = self.overrides.to_dict()

        field_dict: dict[str, Any] = {}

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

        return content_config
