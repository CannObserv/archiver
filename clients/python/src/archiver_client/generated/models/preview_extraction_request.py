from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.preview_extraction_request_source_spec import PreviewExtractionRequestSourceSpec


T = TypeVar("T", bound="PreviewExtractionRequest")


@_attrs_define
class PreviewExtractionRequest:
    """Request body for POST /api/v1/tools/preview-extraction.

    Attributes:
        source_spec (PreviewExtractionRequestSourceSpec): Candidate SourceSpec document (schema_version, extraction,
            fingerprint). Validated against the v1 schema before any fetch is attempted; a validation failure returns 422
            with the per-field issue list.
        url (str): URL to fetch.
    """

    source_spec: PreviewExtractionRequestSourceSpec
    url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_spec = self.source_spec.to_dict()

        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_spec": source_spec,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.preview_extraction_request_source_spec import (
            PreviewExtractionRequestSourceSpec,
        )

        d = dict(src_dict)
        source_spec = PreviewExtractionRequestSourceSpec.from_dict(d.pop("source_spec"))

        url = d.pop("url")

        preview_extraction_request = cls(
            source_spec=source_spec,
            url=url,
        )

        preview_extraction_request.additional_properties = d
        return preview_extraction_request

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
