from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from dateutil.parser import isoparse

from ..types import UNSET, Unset

T = TypeVar("T", bound="SourceRevisionCachePatch")


@_attrs_define
class SourceRevisionCachePatch:
    """Request body for PATCH /source-revisions/{id}.

    Both fields are optional (omitting leaves the DB column untouched).
    Supplying ``null`` explicitly clears the field.
    Use ``model_dump(exclude_unset=True)`` to distinguish omitted from null.

        Attributes:
            content_cache_expires_at (datetime.datetime | None | Unset):
            content_cache_uri (None | str | Unset):
    """

    content_cache_expires_at: datetime.datetime | None | Unset = UNSET
    content_cache_uri: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
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

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if content_cache_expires_at is not UNSET:
            field_dict["content_cache_expires_at"] = content_cache_expires_at
        if content_cache_uri is not UNSET:
            field_dict["content_cache_uri"] = content_cache_uri

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

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

        source_revision_cache_patch = cls(
            content_cache_expires_at=content_cache_expires_at,
            content_cache_uri=content_cache_uri,
        )

        return source_revision_cache_patch
