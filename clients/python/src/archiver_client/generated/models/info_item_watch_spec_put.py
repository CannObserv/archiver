from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.info_item_watch_spec_put_document import InfoItemWatchSpecPutDocument


T = TypeVar("T", bound="InfoItemWatchSpecPut")


@_attrs_define
class InfoItemWatchSpecPut:
    """Request body for PUT /info-items/{id}/watch-spec.

    Replaces the whole document — this is not a merge. Omitting ``interval`` is
    how "the consumer applies its own default" is expressed, so a merge would
    make that state unreachable once an interval had been set.

        Attributes:
            document (InfoItemWatchSpecPutDocument): A WatchSpec v1 document, validated server-side before it is stored.
    """

    document: InfoItemWatchSpecPutDocument

    def to_dict(self) -> dict[str, Any]:
        document = self.document.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "document": document,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_item_watch_spec_put_document import InfoItemWatchSpecPutDocument

        d = dict(src_dict)
        document = InfoItemWatchSpecPutDocument.from_dict(d.pop("document"))

        info_item_watch_spec_put = cls(
            document=document,
        )

        return info_item_watch_spec_put
