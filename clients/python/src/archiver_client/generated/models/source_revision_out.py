from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

T = TypeVar("T", bound="SourceRevisionOut")


@_attrs_define
class SourceRevisionOut:
    """Response body for source-revision endpoints.

    Attributes:
        captured_at (datetime.datetime):
        content_cache_expires_at (datetime.datetime | None):
        content_cache_uri (None | str):
        content_fingerprint (str):
        content_media_type (None | str):
        content_size_bytes (int | None):
        info_source_id (str):
        source_revision_id (str):
    """

    captured_at: datetime.datetime
    content_cache_expires_at: datetime.datetime | None
    content_cache_uri: None | str
    content_fingerprint: str
    content_media_type: None | str
    content_size_bytes: int | None
    info_source_id: str
    source_revision_id: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        captured_at = self.captured_at.isoformat()

        content_cache_expires_at: None | str
        if isinstance(self.content_cache_expires_at, datetime.datetime):
            content_cache_expires_at = self.content_cache_expires_at.isoformat()
        else:
            content_cache_expires_at = self.content_cache_expires_at

        content_cache_uri: None | str
        content_cache_uri = self.content_cache_uri

        content_fingerprint = self.content_fingerprint

        content_media_type: None | str
        content_media_type = self.content_media_type

        content_size_bytes: int | None
        content_size_bytes = self.content_size_bytes

        info_source_id = self.info_source_id

        source_revision_id = self.source_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "captured_at": captured_at,
                "content_cache_expires_at": content_cache_expires_at,
                "content_cache_uri": content_cache_uri,
                "content_fingerprint": content_fingerprint,
                "content_media_type": content_media_type,
                "content_size_bytes": content_size_bytes,
                "info_source_id": info_source_id,
                "source_revision_id": source_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        captured_at = isoparse(d.pop("captured_at"))

        def _parse_content_cache_expires_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                content_cache_expires_at_type_0 = isoparse(data)

                return content_cache_expires_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        content_cache_expires_at = _parse_content_cache_expires_at(
            d.pop("content_cache_expires_at")
        )

        def _parse_content_cache_uri(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        content_cache_uri = _parse_content_cache_uri(d.pop("content_cache_uri"))

        content_fingerprint = d.pop("content_fingerprint")

        def _parse_content_media_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        content_media_type = _parse_content_media_type(d.pop("content_media_type"))

        def _parse_content_size_bytes(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        content_size_bytes = _parse_content_size_bytes(d.pop("content_size_bytes"))

        info_source_id = d.pop("info_source_id")

        source_revision_id = d.pop("source_revision_id")

        source_revision_out = cls(
            captured_at=captured_at,
            content_cache_expires_at=content_cache_expires_at,
            content_cache_uri=content_cache_uri,
            content_fingerprint=content_fingerprint,
            content_media_type=content_media_type,
            content_size_bytes=content_size_bytes,
            info_source_id=info_source_id,
            source_revision_id=source_revision_id,
        )

        source_revision_out.additional_properties = d
        return source_revision_out

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
