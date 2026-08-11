from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ChangeRevisionResponse")


@_attrs_define
class ChangeRevisionResponse:
    """One ChangeRevision record for a WatchedItem.

    ``archiver_revision_id`` was removed in #253: Archiver allocates the registry
    id on its side of ``content.revisions`` and never reports it back, so the
    field could only ever have been null. A **breaking** response change, taken
    deliberately over shipping a permanently-null field that reads as "not synced
    yet". The column survives on the model, holding the 23 ids captured while the
    HTTP write path existed.

        Attributes:
            id (str):
            watched_item_id (str):
            content_fingerprint (str):
            captured_at (datetime.datetime):
            content_size_bytes (int | None):
            schema_version (int):
    """

    id: str
    watched_item_id: str
    content_fingerprint: str
    captured_at: datetime.datetime
    content_size_bytes: int | None
    schema_version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        watched_item_id = self.watched_item_id

        content_fingerprint = self.content_fingerprint

        captured_at = self.captured_at.isoformat()

        content_size_bytes: int | None
        content_size_bytes = self.content_size_bytes

        schema_version = self.schema_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "watched_item_id": watched_item_id,
                "content_fingerprint": content_fingerprint,
                "captured_at": captured_at,
                "content_size_bytes": content_size_bytes,
                "schema_version": schema_version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        watched_item_id = d.pop("watched_item_id")

        content_fingerprint = d.pop("content_fingerprint")

        captured_at = datetime.datetime.fromisoformat(d.pop("captured_at"))

        def _parse_content_size_bytes(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        content_size_bytes = _parse_content_size_bytes(d.pop("content_size_bytes"))

        schema_version = d.pop("schema_version")

        change_revision_response = cls(
            id=id,
            watched_item_id=watched_item_id,
            content_fingerprint=content_fingerprint,
            captured_at=captured_at,
            content_size_bytes=content_size_bytes,
            schema_version=schema_version,
        )

        change_revision_response.additional_properties = d
        return change_revision_response

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
