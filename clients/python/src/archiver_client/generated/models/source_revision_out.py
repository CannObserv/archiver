from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="SourceRevisionOut")


@_attrs_define
class SourceRevisionOut:
    """Response body for source-revision endpoints.

    Attributes:
        captured_at (datetime.datetime): UTC timestamp when the content was fetched and this revision recorded.
        content_cache_expires_at (datetime.datetime | None): UTC timestamp after which the cached content at
            content_cache_uri expires.
        content_cache_uri (None | str): Watcher's scratch-file URI for the cached fetch (e.g. a file:// path). Null
            after cache expiry or explicit clearance.
        content_fingerprint (str): Content hash in 'sha256:<64 hex chars>' format. Together with info_source_id, forms
            the idempotency key.
        content_media_type (None | str): MIME type of the fetched content (e.g. 'text/html'), if recorded.
        content_size_bytes (int | None): Size of the fetched content in bytes, if recorded.
        info_source_id (str): ULID of the InfoSource this revision was captured from.
        source_revision_id (str): ULID identifying this SourceRevision.
        command_id (None | str | Unset): Correlation id of the content.fetch command behind these bytes. Null on rows
            written through this API.
        source_media_type (None | str | Unset): MIME type the origin served, as against content_media_type, which
            describes the extracted content. Null on rows written through this API — only the content.revisions consumer
            observes it.
        spec_fingerprint (None | str | Unset): Identifies the source_specs the producer extracted under. Recorded for
            attribution, never enforced: a value differing from the InfoSource's current specs does not invalidate the
            revision. Null on rows written through this API.
    """

    captured_at: datetime.datetime
    content_cache_expires_at: datetime.datetime | None
    content_cache_uri: None | str
    content_fingerprint: str
    content_media_type: None | str
    content_size_bytes: int | None
    info_source_id: str
    source_revision_id: str
    command_id: None | str | Unset = UNSET
    source_media_type: None | str | Unset = UNSET
    spec_fingerprint: None | str | Unset = UNSET
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

        command_id: None | str | Unset
        if isinstance(self.command_id, Unset):
            command_id = UNSET
        else:
            command_id = self.command_id

        source_media_type: None | str | Unset
        if isinstance(self.source_media_type, Unset):
            source_media_type = UNSET
        else:
            source_media_type = self.source_media_type

        spec_fingerprint: None | str | Unset
        if isinstance(self.spec_fingerprint, Unset):
            spec_fingerprint = UNSET
        else:
            spec_fingerprint = self.spec_fingerprint

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
        if command_id is not UNSET:
            field_dict["command_id"] = command_id
        if source_media_type is not UNSET:
            field_dict["source_media_type"] = source_media_type
        if spec_fingerprint is not UNSET:
            field_dict["spec_fingerprint"] = spec_fingerprint

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

        def _parse_command_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        command_id = _parse_command_id(d.pop("command_id", UNSET))

        def _parse_source_media_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_media_type = _parse_source_media_type(d.pop("source_media_type", UNSET))

        def _parse_spec_fingerprint(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        spec_fingerprint = _parse_spec_fingerprint(d.pop("spec_fingerprint", UNSET))

        source_revision_out = cls(
            captured_at=captured_at,
            content_cache_expires_at=content_cache_expires_at,
            content_cache_uri=content_cache_uri,
            content_fingerprint=content_fingerprint,
            content_media_type=content_media_type,
            content_size_bytes=content_size_bytes,
            info_source_id=info_source_id,
            source_revision_id=source_revision_id,
            command_id=command_id,
            source_media_type=source_media_type,
            spec_fingerprint=spec_fingerprint,
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
