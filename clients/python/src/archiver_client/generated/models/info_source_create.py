from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.info_source_create_source_specs_item import InfoSourceCreateSourceSpecsItem


T = TypeVar("T", bound="InfoSourceCreate")


@_attrs_define
class InfoSourceCreate:
    """Request body for POST /info-sources.

    Attributes:
        source_specs (list[InfoSourceCreateSourceSpecsItem]): Ordered list of extraction specs. First element is the
            primary strategy; subsequent elements are cross-check alternatives. All must share a content-kind family
            (html_text or json). Each element is a SourceSpec v1 document (schema_version, extraction, fingerprint — no
            target section).
        url (str): URL to fetch. Immutable after creation.
    """

    source_specs: list[InfoSourceCreateSourceSpecsItem]
    url: str

    def to_dict(self) -> dict[str, Any]:
        source_specs = []
        for source_specs_item_data in self.source_specs:
            source_specs_item = source_specs_item_data.to_dict()
            source_specs.append(source_specs_item)

        url = self.url

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source_specs": source_specs,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_source_create_source_specs_item import InfoSourceCreateSourceSpecsItem

        d = dict(src_dict)
        source_specs = []
        _source_specs = d.pop("source_specs")
        for source_specs_item_data in _source_specs:
            source_specs_item = InfoSourceCreateSourceSpecsItem.from_dict(source_specs_item_data)

            source_specs.append(source_specs_item)

        url = d.pop("url")

        info_source_create = cls(
            source_specs=source_specs,
            url=url,
        )

        return info_source_create
