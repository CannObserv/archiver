from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.info_source_create_source_spec import InfoSourceCreateSourceSpec


T = TypeVar("T", bound="InfoSourceCreate")


@_attrs_define
class InfoSourceCreate:
    """Request body for POST /info-sources.

    A root source is created when ``parent_info_source_id`` is omitted; the
    ``source_spec`` must then carry ``target.url``. A fragment is created when
    ``parent_info_source_id`` is supplied; the ``source_spec`` must NOT carry
    ``target.url`` — fragments inherit URL/fetch semantics from the parent.

    ``schema_version`` is read from the embedded source_spec document; clients
    must not supply it separately.

        Attributes:
            source_spec (InfoSourceCreateSourceSpec): A SourceSpec v1 document. Validated against the v1 JSON Schema.
            parent_info_source_id (None | str | Unset): ULID of an existing root InfoSource. Required for fragment creation;
                omit for root creation.
    """

    source_spec: InfoSourceCreateSourceSpec
    parent_info_source_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        source_spec = self.source_spec.to_dict()

        parent_info_source_id: None | str | Unset
        if isinstance(self.parent_info_source_id, Unset):
            parent_info_source_id = UNSET
        else:
            parent_info_source_id = self.parent_info_source_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source_spec": source_spec,
            }
        )
        if parent_info_source_id is not UNSET:
            field_dict["parent_info_source_id"] = parent_info_source_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.info_source_create_source_spec import InfoSourceCreateSourceSpec

        d = dict(src_dict)
        source_spec = InfoSourceCreateSourceSpec.from_dict(d.pop("source_spec"))

        def _parse_parent_info_source_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        parent_info_source_id = _parse_parent_info_source_id(d.pop("parent_info_source_id", UNSET))

        info_source_create = cls(
            source_spec=source_spec,
            parent_info_source_id=parent_info_source_id,
        )

        return info_source_create
