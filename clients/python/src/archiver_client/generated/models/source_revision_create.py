from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="SourceRevisionCreate")


@_attrs_define
class SourceRevisionCreate:
    """Request body for POST /source-revisions.

    ``source_revision_id`` is optional and may be supplied by the client
    (e.g. Watcher) so the scratch file at ``content_cache_uri`` can be
    written under its final filename BEFORE the POST round-trips. When
    omitted, the server allocates a ULID. Idempotency on
    ``(info_source_id, content_fingerprint)`` still wins on re-POST —
    a client-supplied ULID is honored on fresh inserts only; existing
    rows are returned as-is.

        Attributes:
            captured_at (datetime.datetime):
            content_fingerprint (str):
            info_source_id (str):
            content_cache_expires_at (datetime.datetime | None | Unset):
            content_cache_uri (None | str | Unset):
            content_media_type (None | str | Unset):
            content_size_bytes (int | None | Unset):
            source_revision_id (None | str | Unset):
    """

    captured_at: datetime.datetime
    content_fingerprint: str
    info_source_id: str
    content_cache_expires_at: datetime.datetime | None | Unset = UNSET
    content_cache_uri: None | str | Unset = UNSET
    content_media_type: None | str | Unset = UNSET
    content_size_bytes: int | None | Unset = UNSET
    source_revision_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        captured_at = self.captured_at.isoformat()

        content_fingerprint = self.content_fingerprint

        info_source_id = self.info_source_id

        content_cache_expires_at: None | str | Unset
        if isinstance(self.content_cache_expires_at, Unset):
            content_cache_expires_at = UNSET
        elif isinstance(self.content_cache_expires_at, datetime.datetime):
            content_cache_expires_at = self.content_cache_expires_at.isoformat()
        else:
            content_cache_expires_at = self.content_cache_expires_at

        content_cache_uri: None | str | Unset
        if isinstance(self.content_cache_uri, Unset):
            content_cache_uri = UNSET
        else:
            content_cache_uri = self.content_cache_uri

        content_media_type: None | str | Unset
        if isinstance(self.content_media_type, Unset):
            content_media_type = UNSET
        else:
            content_media_type = self.content_media_type

        content_size_bytes: int | None | Unset
        if isinstance(self.content_size_bytes, Unset):
            content_size_bytes = UNSET
        else:
            content_size_bytes = self.content_size_bytes

        source_revision_id: None | str | Unset
        if isinstance(self.source_revision_id, Unset):
            source_revision_id = UNSET
        else:
            source_revision_id = self.source_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "captured_at": captured_at,
                "content_fingerprint": content_fingerprint,
                "info_source_id": info_source_id,
            }
        )
        if content_cache_expires_at is not UNSET:
            field_dict["content_cache_expires_at"] = content_cache_expires_at
        if content_cache_uri is not UNSET:
            field_dict["content_cache_uri"] = content_cache_uri
        if content_media_type is not UNSET:
            field_dict["content_media_type"] = content_media_type
        if content_size_bytes is not UNSET:
            field_dict["content_size_bytes"] = content_size_bytes
        if source_revision_id is not UNSET:
            field_dict["source_revision_id"] = source_revision_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        captured_at = isoparse(d.pop("captured_at"))

        content_fingerprint = d.pop("content_fingerprint")

        info_source_id = d.pop("info_source_id")

        def _parse_content_cache_expires_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                content_cache_expires_at_type_0 = isoparse(data)

                return content_cache_expires_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        content_cache_expires_at = _parse_content_cache_expires_at(
            d.pop("content_cache_expires_at", UNSET)
        )

        def _parse_content_cache_uri(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_cache_uri = _parse_content_cache_uri(d.pop("content_cache_uri", UNSET))

        def _parse_content_media_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_media_type = _parse_content_media_type(d.pop("content_media_type", UNSET))

        def _parse_content_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        content_size_bytes = _parse_content_size_bytes(d.pop("content_size_bytes", UNSET))

        def _parse_source_revision_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_revision_id = _parse_source_revision_id(d.pop("source_revision_id", UNSET))

        source_revision_create = cls(
            captured_at=captured_at,
            content_fingerprint=content_fingerprint,
            info_source_id=info_source_id,
            content_cache_expires_at=content_cache_expires_at,
            content_cache_uri=content_cache_uri,
            content_media_type=content_media_type,
            content_size_bytes=content_size_bytes,
            source_revision_id=source_revision_id,
        )

        source_revision_create.additional_properties = d
        return source_revision_create

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
