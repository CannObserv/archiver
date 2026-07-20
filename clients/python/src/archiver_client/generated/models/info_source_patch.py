from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.info_source_patch_source_specs_item import InfoSourcePatchSourceSpecsItem


T = TypeVar("T", bound="InfoSourcePatch")


@_attrs_define
class InfoSourcePatch:
    """Request body for PATCH /info-sources/{id}/source-specs.

    Attributes:
        source_specs (list[InfoSourcePatchSourceSpecsItem]): Replacement source_specs list. Same constraints as on
            creation.
    """

    source_specs: list[InfoSourcePatchSourceSpecsItem]

    def to_dict(self) -> dict[str, Any]:
        source_specs = []
        for source_specs_item_data in self.source_specs:
            source_specs_item = source_specs_item_data.to_dict()
            source_specs.append(source_specs_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source_specs": source_specs,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_source_patch_source_specs_item import InfoSourcePatchSourceSpecsItem

        d = dict(src_dict)
        source_specs = []
        _source_specs = d.pop("source_specs")
        for source_specs_item_data in _source_specs:
            source_specs_item = InfoSourcePatchSourceSpecsItem.from_dict(source_specs_item_data)

            source_specs.append(source_specs_item)

        info_source_patch = cls(
            source_specs=source_specs,
        )

        return info_source_patch
