from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="InfoItemPrimarySourcePut")


@_attrs_define
class InfoItemPrimarySourcePut:
    """Request body for PUT /info-items/{id}/primary-source (archiver#45).

    Attributes:
        info_source_id (str): ULID of an existing InfoSource to make the item's primary.
    """

    info_source_id: str

    def to_dict(self) -> dict[str, Any]:
        info_source_id = self.info_source_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "info_source_id": info_source_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        info_source_id = d.pop("info_source_id")

        info_item_primary_source_put = cls(
            info_source_id=info_source_id,
        )

        return info_item_primary_source_put
