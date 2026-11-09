from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

T = TypeVar("T", bound="InfoItemTagsPut")


@_attrs_define
class InfoItemTagsPut:
    """Request body for PUT /info-items/{id}/tags (archiver#362).

    The whole set, replacing what is stored: ``[]`` clears it. ``tags`` is
    required, so clearing is said, never implied by an omitted field.

        Attributes:
            tags (list[str]): The item's new tag set. Each tag is stripped, then must be non-empty, at most 255 characters,
                and free of commas and control characters. Case is kept; exact duplicates are dropped; at most 32 distinct tags.
                Stored sorted.
    """

    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        tags = self.tags

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "tags": tags,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        tags = cast(list[str], d.pop("tags"))

        info_item_tags_put = cls(
            tags=tags,
        )

        return info_item_tags_put
